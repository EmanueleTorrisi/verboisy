# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verify a received analytical bundle without its original ledger or provider."""

import gzip
import hashlib
import re
import zlib
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

from verboisy.streaming.analytics_contract import DEFAULT_OUTPUT_BYTES, MAX_SHARDS, columns_for
from verboisy.streaming.analytics_verify_io import (
    BLOCK_BYTES,
    CheckedReader,
    DecodedBudget,
    regular_file,
    stable_directory,
)
from verboisy.streaming.contract import StreamError
from verboisy.utils.json_payload import decode_json

DEFAULT_DECODED_BYTES = 128 * 1024**3
DEFAULT_ROW_BYTES = 1024**2
MAX_ROW_BYTES = 16 * 1024**2
_MAX_MANIFEST_BYTES = 8 * 1024**2
_MAX_INTEGER = 2**63 - 1
_MAX_PROOF_ROW_BYTES = 4096
_DIGEST = re.compile(r"[0-9a-f]{64}")
_JOB = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class AnalyticsVerification:
    """Local byte and proof checks, independent of authenticity and source truth."""

    manifest_sha256: str
    manifest_pinned: bool
    format: str
    rows: int
    proof_rows_verified: int
    data_rows_verified: int | None
    shards: int
    bundle_bytes: int
    decoded_bytes: int
    source_replayed: bool = False


@dataclass(frozen=True)
class _File:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class _Shard:
    rows: int
    data: _File
    proof: _File


@dataclass(frozen=True)
class _Manifest:
    job: str
    format: str
    source_format: str
    rows: int
    shards: tuple[_Shard, ...]


def _integer(value: object, name: str, low: int, high: int = _MAX_INTEGER) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise StreamError(f"{name} must be an integer from {low} to {high}")
    return value


def _object(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != fields:
        raise StreamError(f"Invalid analytical {name} fields")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise StreamError("Analytical SHA-256 must be 64 lowercase hexadecimal characters")
    return value


def _file(value: object, name: str) -> _File:
    entry = _object(value, {"name", "bytes", "sha256"}, "file")
    if entry["name"] != name:
        raise StreamError("Analytical shard filename is not canonical")
    return _File(name, _integer(entry["bytes"], "Shard bytes", 1), _digest(entry["sha256"]))


def _manifest(raw: bytes) -> _Manifest:
    value = _object(
        decode_json(raw),
        {
            "version",
            "job_id",
            "format",
            "compression",
            "rows",
            "schema",
            "column_contract",
            "source",
            "row_digest",
            "shards",
            "truth_verified",
            "global_completeness_claimed",
        },
        "manifest",
    )
    job, fmt = value["job_id"], value["format"]
    if (
        value["version"] != "stream-analytics-1"
        or not isinstance(job, str)
        or _JOB.fullmatch(job) is None
        or not isinstance(value["schema"], dict)
        or value["row_digest"] != "sha256_of_verified_utf8_json_before_encoding"
        or value["truth_verified"] is not False
        or value["global_completeness_claimed"] is not False
    ):
        raise StreamError("Unsupported analytical manifest contract")
    if (fmt, value["compression"]) == ("jsonl.gz", "gzip"):
        columns_for("jsonl", value["column_contract"])
    elif (fmt, value["compression"]) == ("parquet", "zstd"):
        columns_for("parquet", value["column_contract"])
    else:
        raise StreamError("Unsupported analytical format or compression")
    source = _object(
        value["source"],
        {"bytes", "sha256", "format", "contract_sha256", "capture_included"},
        "source",
    )
    source_format = source["format"]
    if (
        source_format not in ("csv", "tsv", "jsonl", "text")
        or source["capture_included"] is not False
    ):
        raise StreamError("Unsupported analytical source contract")
    _integer(source["bytes"], "Captured source bytes", 0)
    _digest(source["sha256"])
    _digest(source["contract_sha256"])
    rows = _integer(value["rows"], "Analytical rows", 0)
    shards = value["shards"]
    if not isinstance(shards, list) or not 1 <= len(shards) <= MAX_SHARDS:
        raise StreamError("Analytical bundle has an invalid shard inventory")
    output: list[_Shard] = []
    offset = 1
    for index, entry in enumerate(shards):
        shard = _object(entry, {"first_output_row", "rows", "data", "evidence"}, "shard")
        first = _integer(shard["first_output_row"], "First output row", 1)
        count = _integer(shard["rows"], "Rows per shard", 0 if rows == 0 else 1, 1_000_000)
        if first != offset or (rows == 0 and len(shards) != 1):
            raise StreamError("Analytical shard ranges are not contiguous")
        stem = f"part-{index:05d}"
        output.append(
            _Shard(
                count,
                _file(shard["data"], f"{stem}.{fmt}"),
                _file(shard["evidence"], f"{stem}.evidence.jsonl.gz"),
            )
        )
        offset += count
    if offset - 1 != rows:
        raise StreamError("Analytical manifest and shard row counts differ")
    return _Manifest(job, fmt, source_format, rows, tuple(output))


def _read_shard(stack: ExitStack, root: Path, file: _File) -> CheckedReader:
    stream, size = stack.enter_context(regular_file(root / file.name, file.size))
    if size != file.size:
        raise StreamError("Analytical shard byte count differs from the manifest")
    return stack.enter_context(CheckedReader(stream, size))


def _proof(
    raw: bytes,
    manifest: _Manifest,
    ordinal: int,
    last_line: int,
) -> tuple[int, str]:
    value = _object(
        decode_json(raw),
        {"output_row", "source_row", "line_start", "line_end", "record_id", "output_sha256"},
        "proof row",
    )
    first = _integer(value["line_start"], "Source line start", last_line + 1)
    last = _integer(value["line_end"], "Source line end", first)
    record_id = hashlib.sha256(f"verboisy:stream:{manifest.job}:{ordinal}".encode()).hexdigest()
    if (
        _integer(value["output_row"], "Output row", 1) != ordinal
        or _integer(value["source_row"], "Source row", 1) != ordinal
        or (manifest.source_format in ("jsonl", "text") and first != last)
        or _digest(value["record_id"]) != record_id
    ):
        raise StreamError("Analytical proof coordinates or record identity differ")
    return last, _digest(value["output_sha256"])


def _verify_shard(
    root: Path,
    shard: _Shard,
    manifest: _Manifest,
    ordinal: int,
    last_line: int,
    budget: DecodedBudget,
    row_limit: int,
) -> int:
    with ExitStack() as stack:
        raw_data = _read_shard(stack, root, shard.data)
        raw_proof = _read_shard(stack, root, shard.proof)
        proofs = stack.enter_context(gzip.GzipFile(fileobj=cast(BinaryIO, raw_proof), mode="rb"))
        data: gzip.GzipFile | None = None
        if manifest.format == "jsonl.gz":
            data = stack.enter_context(gzip.GzipFile(fileobj=cast(BinaryIO, raw_data), mode="rb"))
        else:
            while raw_data.read(BLOCK_BYTES):
                pass
        for number in range(ordinal, ordinal + shard.rows):
            last_line, wanted = _proof(
                budget.line(proofs, _MAX_PROOF_ROW_BYTES), manifest, number, last_line
            )
            if data is not None:
                raw = budget.line(data, row_limit)
                if hashlib.sha256(raw).hexdigest() != wanted or not isinstance(
                    decode_json(raw), dict
                ):
                    raise StreamError("Analytical row JSON or digest differs from its proof")
        if proofs.read(1) or (data is not None and data.read(1)):
            raise StreamError("Analytical shard has extra rows")
        raw_data.finish(shard.data.sha256)
        raw_proof.finish(shard.proof.sha256)
    return last_line


def verify_stream_analytics(
    directory: Path,
    *,
    expected_manifest_sha256: str | None = None,
    require_row_checks: bool = False,
    max_bundle_bytes: int = DEFAULT_OUTPUT_BYTES,
    max_decoded_bytes: int = DEFAULT_DECODED_BYTES,
    max_row_bytes: int = DEFAULT_ROW_BYTES,
) -> AnalyticsVerification:
    """Verify received shard bytes, ordered proofs, and all gzip JSONL row digests.

    Parquet payloads are not decoded; require_row_checks refuses those bundles.
    The optional trusted digest pins the exact manifest bytes. Without it the
    result proves internal consistency only. Use a quiescent local directory.
    Neither mode replays the original source or claims source truth.
    """
    _integer(max_bundle_bytes, "Bundle byte limit", 1)
    _integer(max_decoded_bytes, "Decoded byte limit", 1)
    _integer(max_row_bytes, "Row byte limit", 1, MAX_ROW_BYTES)
    if not isinstance(require_row_checks, bool):
        raise StreamError("Require-row-checks must be a boolean")
    pin = None if expected_manifest_sha256 is None else _digest(expected_manifest_sha256)
    directory = directory.absolute()
    try:
        with stable_directory(directory):
            manifest_limit = min(_MAX_MANIFEST_BYTES, max_bundle_bytes)
            with regular_file(directory / "manifest.json", manifest_limit) as (stream, size):
                raw = stream.read(size + 1)
                if len(raw) != size:
                    raise StreamError("Analytical manifest changed while reading")
            fingerprint = hashlib.sha256(raw).hexdigest()
            if pin is not None and pin != fingerprint:
                raise StreamError("Analytical manifest SHA-256 differs from the expected digest")
            manifest = _manifest(raw)
            decoded_rows = manifest.format == "jsonl.gz"
            if require_row_checks and not decoded_rows:
                raise StreamError("Row payload verification is available only for gzip JSONL")
            files = [file for shard in manifest.shards for file in (shard.data, shard.proof)]
            total = size + sum(file.size for file in files)
            if total > max_bundle_bytes:
                raise StreamError("Analytical bundle exceeds its byte limit")
            remaining = {"manifest.json", *(file.name for file in files)}
            for member in directory.iterdir():
                if member.name not in remaining:
                    raise StreamError("Analytical bundle contains an unlisted file")
                remaining.remove(member.name)
            if remaining:
                raise StreamError("Analytical bundle is missing a listed file")
            budget = DecodedBudget(max_decoded_bytes)
            ordinal, last_line = 1, 0
            for shard in manifest.shards:
                last_line = _verify_shard(
                    directory,
                    shard,
                    manifest,
                    ordinal,
                    last_line,
                    budget,
                    max_row_bytes,
                )
                ordinal += shard.rows
    except (OSError, EOFError, ValueError, zlib.error) as error:
        raise StreamError("Cannot read a complete, valid analytical bundle") from error
    return AnalyticsVerification(
        fingerprint,
        pin is not None,
        manifest.format,
        manifest.rows,
        ordinal - 1,
        manifest.rows if decoded_rows else None,
        len(manifest.shards),
        total,
        max_decoded_bytes - budget.remaining,
    )
