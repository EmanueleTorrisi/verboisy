# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded local preparation: durable rows and checkpoints, never a million-row result list."""

from __future__ import annotations

import io
import json
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.request import url2pathname

from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import SourceRow
from verboisy.extractor.projection import project_row
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.streaming.capture import capture_file, verify_capture
from verboisy.streaming.contract import BATCH_ROWS, FORMATS, StreamError, StreamLimits, StreamResult
from verboisy.streaming.ledger import ChunkReader, StreamLedger
from verboisy.streaming.parser import source_rows
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def captured_rows(ledger: StreamLedger, job: dict[str, Any]) -> Generator[SourceRow, None, None]:
    contract = json.loads(job["contract"])
    if contract["format"] == "asset":
        encoded = json.dumps(
            {"sha256": job["sha256"], "byte_count": job["byte_count"]}, separators=(",", ":")
        )
        yield SourceRow(1, "/", None, None, encoded)
    else:
        yield from source_rows(
            io.BufferedReader(ChunkReader(ledger, job)),
            contract["format"],
            contract["limits"]["max_record_bytes"],
        )


def output_value(row: SourceRow, plan: ProjectionPlan | None, ceiling: int) -> str:
    value = row.values_json if plan is None else project_row(row, plan).values_json
    if len(value.encode("utf-8")) > ceiling:
        raise StreamError("Streaming projected record byte limit exceeded")
    return value


def stream_dataset(
    *,
    database: Path,
    source: Path | None = None,
    dataset_format: str | None = None,
    schema: dict[str, Any] | None = None,
    projection: ProjectionPlan | None = None,
    config: Settings | None = None,
    resume: str | None = None,
    limits: StreamLimits | None = None,
    rows_per_invocation: int | None = None,
    export: Path | None = None,
    csv_mode: Literal["spreadsheet", "json"] | None = None,
    protected_inputs: tuple[Path, ...] | None = None,
) -> StreamResult:
    """Prepare rows under a fixed contract; resume replays verified saved bytes.

    Each accepted row and its last-processed ordinal commit in the same bounded
    transaction. A failed/interrupted batch is rolled back, so resume cannot skip
    observations or create duplicates. Identity is the physical source row, not an
    inferred entity key. Sorting, grouping and semantic research remain in run().
    """
    if csv_mode not in (None, "spreadsheet", "json"):
        raise StreamError("CSV mode must be spreadsheet or json")
    if rows_per_invocation is not None and (
        isinstance(rows_per_invocation, bool)
        or not isinstance(rows_per_invocation, int)
        or rows_per_invocation < 1
    ):
        raise StreamError("Invocation row budget must be a positive integer")
    if resume is not None:
        if any(
            value is not None
            for value in (
                source,
                dataset_format,
                schema,
                projection,
                limits,
                csv_mode,
                protected_inputs,
            )
        ):
            raise StreamError("Resume uses the saved streaming contract")
    elif source is None or dataset_format not in FORMATS:
        raise StreamError("Choose a local source and csv, tsv, jsonl, text or asset format")
    if source is not None and (
        source.resolve() == database.resolve()
        or (source.exists() and database.exists() and source.samefile(database))
    ):
        raise StreamError("Source cannot be the streaming ledger")
    execution_config = config or Settings()
    normalized = SchemaBuilder.normalize(schema or {}) if resume is None else None
    chosen = limits or StreamLimits()
    with closing(StreamLedger(database, max_storage_bytes=chosen.max_storage_bytes)) as ledger:
        db = ledger.connection
        if resume is None:
            assert source is not None
            job_id = uuid.uuid4().hex
            contract: dict[str, Any] = {
                "version": "1",
                "csv_mode": csv_mode or "spreadsheet",
                "protected_inputs": sorted(
                    str(p.resolve())
                    for p in (*(protected_inputs or ()), *execution_config.input_files())
                ),
                "source_uri": source.absolute().as_uri(),
                "format": dataset_format,
                "schema": normalized,
                "projection": projection.model_dump() if projection is not None else None,
                "limits": asdict(chosen),
            }
            with db:
                db.execute(
                    "INSERT INTO stream_jobs(id,contract,status) VALUES(?,?,?)",
                    (job_id, json.dumps(contract), "RUNNING"),
                )
        else:
            job_id = resume
            contract = json.loads(ledger.job(job_id)["contract"])
            chosen = StreamLimits(**contract["limits"])
            projection = (
                ProjectionPlan.model_validate(contract["projection"])
                if contract["projection"] is not None
                else None
            )
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute("PRAGMA page_count").fetchone()[0] * page_size > chosen.max_storage_bytes:
                raise StreamError("Streaming ledger exceeds its saved storage limit")
            db.execute(f"PRAGMA max_page_count={chosen.max_storage_bytes // page_size}")
        root_validator = SchemaBuilder.validator(contract["schema"])
        validator = (
            root_validator.evolve(schema=contract["schema"]["items"])
            if contract["schema"]["type"] == "array"
            else root_validator
        )
        try:
            job = ledger.job(job_id)
            if not job["captured"]:
                capture_file(
                    ledger,
                    job_id,
                    Path(url2pathname(urlsplit(contract["source_uri"]).path)),
                    execution_config,
                    chosen,
                )
                job = ledger.job(job_id)
            verify_capture(ledger, job)
            _ingest(ledger, job, projection, validator, chosen, rows_per_invocation)
        except KeyboardInterrupt:
            with db:
                db.execute(
                    "UPDATE stream_jobs SET status=?,reason=? WHERE id=?",
                    ("PAUSED", "interrupted", job_id),
                )
        except (VerboisyError, OSError) as error:
            with db:
                db.execute(
                    "UPDATE stream_jobs SET status=?,reason=? WHERE id=?",
                    ("FAILED", str(error), job_id),
                )
        except sqlite3.Error:
            # A full disk may also prevent a status write. Last committed rows and
            # their checkpoint remain authoritative; return a resumable outcome.
            job = ledger.job(job_id)
            return _result(job, "PAUSED", "storage_error")
        job = ledger.job(job_id)
        if export is not None and job["status"] == "COMPLETED":
            from verboisy.streaming.export import export_stream

            export_stream(ledger, job, export, protected_inputs=execution_config.input_files())
        return _result(job, job["status"], job["reason"])


def _ingest(
    ledger: StreamLedger,
    job: dict[str, Any],
    plan: ProjectionPlan | None,
    validator: Any,
    limits: StreamLimits,
    budget: int | None,
) -> None:
    db = ledger.connection
    checkpoint, admitted = job["processed"], 0
    batch: list[tuple[Any, ...]] = []
    batch_bytes = 0
    with closing(captured_rows(ledger, job)) as rows:
        for row in rows:
            if row.row_index <= checkpoint:
                continue
            if row.row_index > limits.max_rows:
                raise StreamError("Streaming row limit exceeded")
            value = output_value(row, plan, limits.max_record_bytes)
            if not validator.is_valid(json.loads(value)):
                raise StreamError(f"Streaming schema rejected source row {row.row_index}")
            batch.append(
                (
                    job["id"],
                    row.row_index,
                    row.line_start,
                    row.line_end,
                    row.values_json,
                    None if value == row.values_json else value,
                )
            )
            admitted += 1
            batch_bytes += len(row.values_json.encode("utf-8")) + len(value.encode("utf-8"))
            if (
                len(batch) >= BATCH_ROWS
                or batch_bytes >= 8_388_608
                or (budget is not None and admitted >= budget)
            ):
                _commit(ledger, job["id"], batch)
                batch.clear()
                batch_bytes = 0
            if budget is not None and admitted >= budget:
                with db:
                    db.execute(
                        "UPDATE stream_jobs SET status=?,reason=? WHERE id=?",
                        ("PAUSED", "invocation_row_budget", job["id"]),
                    )
                return
        if batch:
            _commit(ledger, job["id"], batch)
    with db:
        db.execute(
            "UPDATE stream_jobs SET status=?,reason=NULL WHERE id=?", ("COMPLETED", job["id"])
        )


def _commit(ledger: StreamLedger, job_id: str, batch: list[tuple[Any, ...]]) -> None:
    with ledger.connection as db:
        db.executemany("INSERT INTO stream_rows VALUES(?,?,?,?,?,?)", batch)
        db.execute(
            "UPDATE stream_jobs SET processed=?,status=?,reason=NULL WHERE id=?",
            (batch[-1][1], "RUNNING", job_id),
        )


def _result(job: dict[str, Any], status: str, reason: str | None) -> StreamResult:
    return StreamResult(
        job["id"], status, job["processed"], job["byte_count"], job["sha256"], reason
    )
