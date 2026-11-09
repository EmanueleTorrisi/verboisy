# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Export verified stream rows as bounded shards with source coordinates."""

import hashlib
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from verboisy.extractor.dataset import SourceRow
from verboisy.storage.exporters import sync_directory
from verboisy.storage.path_safety import validate_output_paths
from verboisy.streaming.analytics_contract import (
    DEFAULT_OUTPUT_BYTES,
    DEFAULT_SHARD_ROWS,
    MAX_SHARDS,
    SHARD_PAYLOAD_BYTES,
    columns_for,
    json_bytes,
    validate_limits,
)
from verboisy.streaming.analytics_io import OutputBudget, ParquetEncoder, Sink, jsonl_writer
from verboisy.streaming.contract import StreamError
from verboisy.streaming.integrity import validated_job, verified_export_rows
from verboisy.streaming.ledger import StreamLedger

_Writer = Callable[[Sink], AbstractContextManager[Callable[[bytes], None]]]


@dataclass(frozen=True)
class AnalyticalExport:
    manifest: Path
    rows: int
    shards: int
    output_bytes: int


def export_stream_analytics(
    *,
    database: Path,
    job_id: str,
    output_dir: Path,
    output_format: str = "jsonl",
    column_contract: dict[str, Any] | None = None,
    shard_rows: int = DEFAULT_SHARD_ROWS,
    max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
) -> AnalyticalExport:
    """Export a completed stream in source order without modifying its ledger.

    JSONL shards are gzip compressed. Parquet uses a declared flat schema and
    optional PyArrow, with explicit JSON text columns for nested values. Each
    shard has a compressed evidence file with row coordinates and digests. The
    capture stays in the ledger for full replay. Use a new directory, and read
    it only once manifest.json exists; an interrupted export has no manifest.
    """
    columns = columns_for(output_format, column_contract)
    validate_limits(shard_rows, max_output_bytes)
    with closing(StreamLedger(database, read_only=True)) as ledger:
        try:
            ledger.connection.execute("BEGIN")
        except sqlite3.Error as error:
            raise StreamError("Cannot open a consistent streaming ledger snapshot") from error
        job = validated_job(ledger, job_id)
        if job["status"] != "COMPLETED":
            raise StreamError("Analytical export requires a completed streaming job")
        contract = job["_contract"]
        if contract["format"] == "asset":
            raise StreamError("Opaque assets do not have analytical rows")
        extension, compression = ("parquet", "zstd") if columns else ("jsonl.gz", "gzip")
        writer: _Writer = ParquetEncoder(columns).writer if columns else jsonl_writer
        sidecars = ("", ".lock", "-wal", "-shm", "-journal")
        protected = {
            *(Path(str(ledger.path) + suffix) for suffix in sidecars),
            Path(url2pathname(urlsplit(contract["source_uri"]).path)),
            Path(".env").resolve(),
            *(Path(path) for path in contract.get("protected_inputs", [])),
        }
        try:
            validate_output_paths((output_dir,), protected)
            output_dir.mkdir(mode=0o700)
        except (OSError, ValueError) as error:
            raise StreamError(
                "Analytical export requires a new directory that does not alias an input"
            ) from error
        try:
            budget = OutputBudget(max_output_bytes)
            with closing(verified_export_rows(ledger, job)) as replay:
                shards = _write_shards(
                    ((source, value.encode("utf-8")) for source, value in replay),
                    job_id,
                    output_dir,
                    extension,
                    writer,
                    shard_rows,
                    budget,
                )
            manifest = {
                "version": "stream-analytics-1",
                "job_id": job_id,
                "format": extension,
                "compression": compression,
                "rows": job["processed"],
                "schema": contract["schema"],
                "column_contract": {
                    "version": "1",
                    "columns": [
                        {"name": c.name, "type": c.kind, "nullable": c.nullable} for c in columns
                    ],
                }
                if columns
                else None,
                "source": {
                    "bytes": job["byte_count"],
                    "sha256": job["sha256"],
                    "format": contract["format"],
                    "contract_sha256": hashlib.sha256(json_bytes(contract)).hexdigest(),
                    "capture_included": False,
                },
                "row_digest": "sha256_of_verified_utf8_json_before_encoding",
                "shards": shards,
                "truth_verified": False,
                "global_completeness_claimed": False,
            }
            temporary = output_dir / ".manifest.tmp"
            with Sink(temporary, budget) as sink:
                sink.write(json_bytes(manifest) + b"\n")
                sink.finish()
            sync_directory(output_dir)
            published = output_dir / "manifest.json"
            temporary.replace(published)
            sync_directory(output_dir)
            sync_directory(output_dir.parent)
        except BaseException:
            shutil.rmtree(output_dir)
            raise
    return AnalyticalExport(published, job["processed"], len(shards), budget.used)


def _write_shards(
    rows: Iterator[tuple[SourceRow, bytes]],
    job_id: str,
    folder: Path,
    extension: str,
    writer: _Writer,
    shard_rows: int,
    budget: OutputBudget,
) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    next_row = next(rows, None)
    total = 0
    for index in range(MAX_SHARDS):
        stem = f"part-{index:05d}"
        first = total + 1
        count = size = 0
        with (
            Sink(folder / f"{stem}.{extension}", budget) as data,
            Sink(folder / f"{stem}.evidence.jsonl.gz", budget) as evidence,
        ):
            with writer(data) as write, jsonl_writer(evidence) as proof:
                while next_row is not None and count < shard_rows:
                    source, payload = next_row
                    if count and size + len(payload) > SHARD_PAYLOAD_BYTES:
                        break
                    write(payload)
                    count += 1
                    total += 1
                    size += len(payload)
                    proof(_row_proof(job_id, source, payload, total))
                    next_row = next(rows, None)
            shards.append(
                {
                    "first_output_row": first,
                    "rows": count,
                    "data": data.finish(),
                    "evidence": evidence.finish(),
                }
            )
        if next_row is None:
            return shards
    raise StreamError("Analytical export exceeds the shard count limit")


def _row_proof(job_id: str, source: SourceRow, payload: bytes, output_row: int) -> bytes:
    key = f"verboisy:stream:{job_id}:{source.row_index}".encode()
    return json_bytes(
        {
            "output_row": output_row,
            "source_row": source.row_index,
            "line_start": source.line_start,
            "line_end": source.line_end,
            "record_id": hashlib.sha256(key).hexdigest(),
            "output_sha256": hashlib.sha256(payload).hexdigest(),
        }
    )
