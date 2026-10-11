# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read explicitly granted regular files into the existing immutable asset contract."""

import asyncio
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from verboisy.dataset_formats import MIME_TYPES
from verboisy.extractor.dataset import DatasetFormat, parse_dataset
from verboisy.extractor.download import DatasetDownloadError, DownloadedDataset
from verboisy.utils.config import Settings


def _read_local(
    url: str, config: Settings, dataset_format: DatasetFormat, max_bytes: int
) -> DownloadedDataset:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
            raise DatasetDownloadError(
                "Local sources require canonical file URIs without an authority"
            )
        path = Path(url2pathname(parsed.path))
        if not path.is_absolute() or path.as_uri() != url:
            raise DatasetDownloadError("Local sources require canonical absolute file URIs")
        resolved = path.resolve(strict=True)
        roots = [Path(root).resolve(strict=True) for root in config.dataset_local_roots]
        if not any(resolved.is_relative_to(root) and root.is_dir() for root in roots):
            raise DatasetDownloadError("Local source is outside DATASET_LOCAL_ROOTS")
        expected = resolved.stat()
        if not stat.S_ISREG(expected.st_mode):
            raise DatasetDownloadError("Local source must be a regular file")
        if expected.st_size > max_bytes:
            raise DatasetDownloadError("Local dataset byte limit exceeded")
        # Check the opened object before reading. A replaced final symlink or
        # different inode must not be treated as the file that was authorized.
        with resolved.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
                raise DatasetDownloadError("Local source changed before capture")
            content = stream.read(max_bytes + 1)
            finished = os.fstat(stream.fileno())
        if len(content) > max_bytes:
            raise DatasetDownloadError("Local dataset byte limit exceeded")
        if (opened.st_size, opened.st_mtime_ns) != (finished.st_size, finished.st_mtime_ns) or len(
            content
        ) != finished.st_size:
            raise DatasetDownloadError("Local source changed during capture")
        dataset = parse_dataset(content, dataset_format, max_bytes=max_bytes)
        mime = MIME_TYPES[dataset_format][0]
        return DownloadedDataset(url, url, (url,), mime, None, dataset)
    except (OSError, ValueError) as error:
        raise DatasetDownloadError(f"Local dataset unavailable ({type(error).__name__})") from None


async def load_local_dataset(
    url: str, config: Settings, *, dataset_format: DatasetFormat, max_bytes: int = 16_777_216
) -> DownloadedDataset:
    """Capture once; subsequent resume uses saved bytes rather than the source path."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("Invalid local dataset byte limit")
    return await asyncio.to_thread(_read_local, url, config, dataset_format, max_bytes)
