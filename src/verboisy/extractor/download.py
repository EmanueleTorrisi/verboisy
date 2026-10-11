# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded HTTP acquisition of explicitly declared datasets."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from verboisy.browser.policy import validate_url
from verboisy.dataset_formats import MIME_TYPES
from verboisy.extractor.dataset import DatasetFormat, ParsedDataset, parse_dataset
from verboisy.extractor.transport import PinnedTransport
from verboisy.source_config import dataset_request_headers
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError, VerboisyError


class DatasetDownloadError(VerboisyError):
    """HTTP acquisition failed within the declared scope and resource limits."""


@dataclass(frozen=True)
class DownloadedDataset:
    original_url: str
    final_url: str
    redirect_chain: tuple[str, ...]
    content_type: str
    remote_disposition: str | None
    dataset: ParsedDataset


async def download_dataset(
    url: str,
    config: Settings,
    *,
    dataset_format: DatasetFormat,
    permits: Callable[[str], bool],
    max_bytes: int = 16_777_216,
    max_rows: int = 100_000,
    max_depth: int = 32,
    max_redirects: int = 5,
    timeout_seconds: float = 30,
) -> DownloadedDataset:
    """Fetch raw bytes with each redirect checked before its destination request.

    Compression is rejected in version 1. Remote filenames are never used as
    filesystem paths. Address validation reuses the existing best-effort network
    policy; the connection backend revalidates and connects to literal addresses.
    """
    if (
        any(
            not isinstance(limit, int) or isinstance(limit, bool)
            for limit in (max_bytes, max_rows, max_depth, max_redirects)
        )
        or max_bytes < 1
        or max_rows < 0
        or max_depth < 1
        or max_redirects < 0
        or timeout_seconds <= 0
        or not math.isfinite(timeout_seconds)
    ):
        raise ValueError("Invalid dataset download limits")
    if dataset_format not in MIME_TYPES:
        raise DatasetDownloadError("Unsupported dataset format")
    chain: list[str] = []
    current = url
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept-Encoding": "identity"},
                transport=PinnedTransport(config),
            ) as client:
                while True:
                    # Check every hop before sending it; rejecting only the final URL
                    # would already have fetched an excluded redirect destination.
                    if not permits(current):
                        raise DatasetDownloadError("Dataset destination is outside declared scope")
                    await validate_url(current, config)
                    if current in chain:
                        raise DatasetDownloadError("Dataset redirect loop")
                    chain.append(current)
                    # Only explicitly configured cookies belong to this hop.
                    # Server-set cookies must not become ambient redirect credentials.
                    client.cookies.clear()
                    async with client.stream(
                        "GET",
                        current,
                        headers=dataset_request_headers(config.dataset_http_headers, current),
                    ) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                raise DatasetDownloadError("Dataset redirect has no location")
                            if len(chain) > max_redirects:
                                raise DatasetDownloadError("Dataset redirect limit exceeded")
                            current = urljoin(current, location)
                            continue
                        if response.status_code != 200:
                            raise DatasetDownloadError(
                                f"Dataset server returned HTTP {response.status_code}"
                            )
                        encoding = (
                            response.headers.get("content-encoding", "identity").strip().lower()
                        )
                        if encoding != "identity":
                            raise DatasetDownloadError(
                                "Compressed dataset responses are unsupported"
                            )
                        mime = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if dataset_format != "asset" and mime not in MIME_TYPES[dataset_format]:
                            raise DatasetDownloadError(
                                "Dataset response has unsupported content type"
                            )
                        length = response.headers.get("content-length")
                        if length is not None:
                            if not length.isascii() or not length.isdecimal():
                                raise DatasetDownloadError("Invalid dataset content length")
                            if int(length) > max_bytes:
                                raise DatasetDownloadError("Dataset byte limit exceeded")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > max_bytes:
                                raise DatasetDownloadError("Dataset byte limit exceeded")
                            body.extend(chunk)
                        if length is not None and len(body) != int(length):
                            raise DatasetDownloadError("Dataset content length mismatch")
                        parsed = parse_dataset(
                            bytes(body),
                            dataset_format,
                            max_bytes=max_bytes,
                            max_rows=max_rows,
                            max_depth=max_depth,
                        )
                        disposition = response.headers.get("content-disposition")
                        return DownloadedDataset(
                            url,
                            current,
                            tuple(chain),
                            mime,
                            disposition[:1024] if disposition is not None else None,
                            parsed,
                        )
    except NavigationError:
        raise DatasetDownloadError("Dataset destination violates network policy") from None
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError) as error:
        raise DatasetDownloadError(
            f"Dataset download unavailable ({type(error).__name__})"
        ) from None
