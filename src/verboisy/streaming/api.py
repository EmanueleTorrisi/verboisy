# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded local preparation: durable rows and checkpoints, never a million-row result list."""

from __future__ import annotations

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
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.streaming.capture import capture_file
from verboisy.streaming.contract import (
    BATCH_ROWS,
    FORMATS,
    StreamError,
    StreamLimits,
    StreamResult,
    validate_stream_schema,
)
from verboisy.streaming.integrity import captured_rows as captured_rows
from verboisy.streaming.integrity import output_value as output_value
from verboisy.streaming.integrity import (
    validate_checkpoint_shape,
    validated_job,
    verified_resume_rows,
)
from verboisy.streaming.ledger import StreamLedger
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import decode_json


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
    if schema is not None and not isinstance(schema, dict):
        raise StreamError("Streaming schema must be a JSON object")
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
    if resume is None:
        validate_stream_schema(schema or {})
    normalized = SchemaBuilder.normalize(schema or {}) if resume is None else None
    if normalized is not None:
        validate_stream_schema(normalized)
    chosen = limits or StreamLimits()
    if resume is not None:
        with closing(StreamLedger(database, read_only=True)) as inspection:
            saved = validated_job(inspection, resume)
            validate_checkpoint_shape(inspection, saved)
            chosen = StreamLimits(**saved["_contract"]["limits"])
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
            saved = validated_job(ledger, job_id)
            contract = saved["_contract"]
            chosen = StreamLimits(**contract["limits"])
            projection = (
                ProjectionPlan.model_validate(contract["projection"])
                if contract["projection"] is not None
                else None
            )
        root_validator = SchemaBuilder.validator(contract["schema"])
        validator = (
            root_validator.evolve(schema=contract["schema"]["items"])
            if contract["schema"]["type"] == "array"
            else root_validator
        )
        job = validated_job(ledger, job_id)
        validate_checkpoint_shape(ledger, job)
        positioned = None
        if export is not None:
            from verboisy.storage.path_safety import validate_output_paths
            from verboisy.streaming.export import bundle_paths

            protected = [
                database,
                Path(url2pathname(urlsplit(contract["source_uri"]).path)),
                *(Path(p) for p in contract.get("protected_inputs", [])),
            ]
            try:
                validate_output_paths(bundle_paths(export), protected)
            except (OSError, ValueError):
                raise StreamError(
                    "Streaming output would overwrite a protected or unsafe path"
                ) from None
        positioned = verified_resume_rows(ledger, job) if job["captured"] else None
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
            if positioned is None:
                positioned = verified_resume_rows(ledger, job)
            _ingest(
                ledger, job, projection, validator, chosen, rows_per_invocation, rows=positioned
            )
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
        finally:
            if positioned is not None:
                positioned.close()
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
    *,
    rows: Generator[SourceRow, None, None] | None = None,
) -> None:
    db = ledger.connection
    admitted = 0
    batch: list[tuple[Any, ...]] = []
    batch_bytes = 0
    with closing(rows if rows is not None else verified_resume_rows(ledger, job)) as rows:
        for row in rows:
            if row.row_index > limits.max_rows:
                raise StreamError("Streaming row limit exceeded")
            value = output_value(row, plan, limits.max_record_bytes)
            if not validator.is_valid(decode_json(value)):
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
