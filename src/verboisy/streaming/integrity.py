# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded source-bound checkpoint validation and coherent public paging.

A stable connection revision caches only a validation stamp, never row payloads.
A resume eagerly verifies the committed prefix once, then reuses its positioned
parser. Corrupt history is rejected without implicit repair or status mutation.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import SourceRow
from verboisy.extractor.projection import project_row
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.streaming.capture import verify_capture
from verboisy.streaming.contract import FORMATS, StreamError, StreamLimits, validate_stream_schema
from verboisy.streaming.ledger import ChunkReader, StreamLedger
from verboisy.streaming.parser import source_rows
from verboisy.streaming.validation import row_validator
from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import decode_json


def validated_job(ledger: StreamLedger, job_id: str) -> dict[str, Any]:
    """Validate saved metadata/types/ceilings and fixed contract without writes."""
    job = ledger.job(job_id)
    try:
        contract = decode_json(job["contract"])
        if (
            not isinstance(contract, dict)
            or contract.get("version") != "1"
            or contract.get("format") not in FORMATS
        ):
            raise ValueError("Invalid saved contract version/format")
        if not isinstance(contract.get("schema"), dict):
            raise ValueError("Missing saved row schema")
        normalized = SchemaBuilder.normalize(contract["schema"])
        validate_stream_schema(normalized)
        if not isinstance(contract.get("limits"), dict):
            raise ValueError("Invalid saved limits")
        limits = StreamLimits(**contract["limits"])
        if contract.get("projection") is not None:
            ProjectionPlan.model_validate(contract["projection"])
        if contract.get("csv_mode", "spreadsheet") not in ("spreadsheet", "json"):
            raise ValueError("Invalid saved CSV mode")
        if not isinstance(contract.get("source_uri"), str):
            raise ValueError("Invalid saved source URI type")
        uri = urlsplit(contract["source_uri"])
        if (
            uri.scheme != "file"
            or uri.netloc not in ("", "localhost")
            or not uri.path.startswith("/")
            or uri.query
            or uri.fragment
        ):
            raise ValueError("Invalid saved source URI")
        paths = contract.get("protected_inputs", [])
        if not isinstance(paths, list) or any(
            not isinstance(p, str) or not Path(p).is_absolute() for p in paths
        ):
            raise ValueError("Invalid protected input paths")
        if (
            not isinstance(job["id"], str)
            or not job["id"]
            or job["status"] not in ("RUNNING", "PAUSED", "FAILED", "COMPLETED")
        ):
            raise ValueError("Invalid saved job identity/status")
        for key, maximum in (
            ("captured", 1),
            ("processed", limits.max_rows),
            ("byte_count", limits.max_input_bytes),
        ):
            if (not isinstance(job[key], int) or isinstance(job[key], bool)) or not 0 <= job[
                key
            ] <= maximum:
                raise ValueError("Invalid saved checkpoint scalar")
        if job["captured"] and (
            not isinstance(job["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", job["sha256"])
        ):
            raise ValueError("Invalid saved capture digest")
        if job["status"] == "COMPLETED" and not job["captured"]:
            raise ValueError("Completed job has no capture")
        job["_contract"] = contract
    except (ValueError, TypeError, KeyError, RecursionError, VerboisyError) as error:
        raise StreamError("Saved streaming contract or checkpoint is invalid") from error
    return job


def validate_checkpoint_shape(ledger: StreamLedger, job: dict[str, Any]) -> None:
    """COUNT and the unique ordinal key prove exactly the committed prefix."""
    try:
        row = ledger.connection.execute(
            "SELECT COUNT(*) AS n,MIN(ordinal) AS lo,MAX(ordinal) AS hi,"
            "SUM(CASE WHEN typeof(ordinal)='integer' THEN 0 ELSE 1 END) AS bad "
            "FROM stream_rows WHERE job_id=?",
            (job["id"],),
        ).fetchone()
        n = job["processed"]
        if (
            row["n"] != n
            or (n and (row["lo"] != 1 or row["hi"] != n or row["bad"]))
            or (n and not job["captured"])
        ):
            raise StreamError("Streaming rows do not match their committed prefix")
    except sqlite3.Error as error:
        raise StreamError("Cannot validate streaming checkpoint") from error


def captured_rows(ledger: StreamLedger, job: dict[str, Any]) -> Generator[SourceRow, None, None]:
    contract = job.get("_contract") or decode_json(job["contract"])
    if contract["format"] == "asset":
        encoded = json.dumps(
            {"sha256": job["sha256"], "byte_count": job["byte_count"]}, separators=(",", ":")
        )
        yield SourceRow(1, "/", None, None, encoded)
    else:
        with io.BufferedReader(ChunkReader(ledger, job)) as stream:
            yield from source_rows(
                stream, contract["format"], contract["limits"]["max_record_bytes"]
            )


def output_value(row: SourceRow, plan: ProjectionPlan | None, ceiling: int) -> str:
    value = row.values_json if plan is None else project_row(row, plan).values_json
    if len(value.encode("utf-8")) > ceiling:
        raise StreamError("Streaming projected record byte limit exceeded")
    return value


def _canonical(text: str) -> str:
    value = decode_json(text)
    if not isinstance(value, dict):
        raise ValueError("Streaming row must be an object")
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def _same_json(saved: str, observed: str) -> bool:
    # Captured parser/projection text is already strict finite JSON. Exact saved
    # bytes can reuse that proof; different spellings require typed decoding.
    return saved == observed or _canonical(saved) == _canonical(observed)


def _verify_row(
    source: SourceRow, saved: Any, plan: ProjectionPlan | None, validator: Any, ceiling: int
) -> str:
    if saved is None:
        raise StreamError("Streaming checkpoint exceeds captured source")
    expected = output_value(source, plan, ceiling)
    if (
        saved["ordinal"] != source.row_index
        or saved["first_line"] != source.line_start
        or saved["last_line"] != source.line_end
        or not _same_json(saved["source_json"], source.values_json)
        or not _same_json(
            saved["output_json"] if saved["output_json"] is not None else saved["source_json"],
            expected,
        )
        or not validator.is_valid(decode_json(expected))
    ):
        raise StreamError("Streaming row evidence differs from captured source")
    return expected


def _row_contract(job: dict[str, Any]) -> tuple[ProjectionPlan | None, Any, int]:
    contract = job["_contract"]
    plan = (
        ProjectionPlan.model_validate(contract["projection"])
        if contract.get("projection") is not None
        else None
    )
    validator = row_validator(contract["schema"])
    return plan, validator, contract["limits"]["max_record_bytes"]


def _saved_rows(ledger: StreamLedger, job: dict[str, Any], ceiling: int) -> sqlite3.Cursor:
    """Do not materialize oversized/tampered SQLite text before rejecting it."""
    return ledger.connection.execute(
        "SELECT ordinal,first_line,last_line,"
        "CASE WHEN typeof(source_json)='text' AND length(CAST(source_json AS BLOB))<=? "
        "THEN source_json ELSE NULL END AS source_json,"
        "CASE WHEN output_json IS NULL THEN NULL "
        "WHEN typeof(output_json)='text' AND length(CAST(output_json AS BLOB))<=? "
        "THEN output_json ELSE 'null' END AS output_json "
        "FROM stream_rows WHERE job_id=? ORDER BY ordinal",
        (ceiling, ceiling, job["id"]),
    )


def verified_export_rows(
    ledger: StreamLedger, job: dict[str, Any]
) -> Generator[tuple[SourceRow, str], None, None]:
    """Verify once while staging; no published target changes until EOF is proven."""
    job = validated_job(ledger, job["id"])
    validate_checkpoint_shape(ledger, job)
    if job["status"] != "COMPLETED":
        raise StreamError("Only completed streaming jobs can publish an export")
    verify_capture(ledger, job)
    plan, validator, ceiling = _row_contract(job)
    cursor = _saved_rows(ledger, job, ceiling)
    rows = captured_rows(ledger, job)
    count = 0
    try:
        for source in rows:
            yield source, _verify_row(source, cursor.fetchone(), plan, validator, ceiling)
            count += 1
        if count != job["processed"] or cursor.fetchone() is not None:
            raise StreamError("Completed streaming checkpoint is not at source EOF")
    except (ValueError, TypeError, sqlite3.Error) as error:
        raise StreamError("Cannot verify streaming export evidence") from error
    finally:
        rows.close()
        cursor.close()


def verified_resume_rows(
    ledger: StreamLedger, job: dict[str, Any]
) -> Generator[SourceRow, None, None]:
    """Eagerly verify capture/prefix and return the same parser positioned at its tail."""
    job = validated_job(ledger, job["id"])
    validate_checkpoint_shape(ledger, job)
    if not job["captured"]:
        raise StreamError("Cannot replay an incomplete capture")
    verify_capture(ledger, job)
    plan, validator, ceiling = _row_contract(job)
    rows = captured_rows(ledger, job)
    cursor = _saved_rows(ledger, job, ceiling)
    try:
        for _ in range(job["processed"]):
            source = next(rows, None)
            saved = cursor.fetchone()
            if source is None or saved is None:
                raise StreamError("Streaming checkpoint exceeds captured source")
            _verify_row(source, saved, plan, validator, ceiling)
        if job["status"] == "COMPLETED" and next(rows, None) is not None:
            raise StreamError("Completed streaming checkpoint is not at source EOF")
    except (ValueError, TypeError, sqlite3.Error) as error:
        rows.close()
        raise StreamError("Cannot verify saved streaming row evidence") from error
    except BaseException:
        rows.close()
        raise
    finally:
        cursor.close()
    return rows


def read_verified_page(
    ledger: StreamLedger, job_id: str, after: int, limit: int
) -> list[dict[str, Any]]:
    """Read a bounded keyset page from one verified snapshot; cache at most 32 stamps."""
    if (
        (not isinstance(after, int) or isinstance(after, bool))
        or after < 0
        or (not isinstance(limit, int) or isinstance(limit, bool))
        or not 1 <= limit <= 1000
    ):
        raise StreamError("Page requires a nonnegative cursor and limit from 1 to 1000")
    db = ledger.connection
    own = not db.in_transaction
    # Revision reads bracket snapshot ownership. A concurrent commit cannot stamp
    # old validation as a new revision, or allow an unverified cache-hit page out.
    for _ in range(3):
        before = (db.execute("PRAGMA data_version").fetchone()[0], db.total_changes)
        if own:
            db.execute("BEGIN")
        try:
            job = validated_job(ledger, job_id)
            stamp = (before, tuple((k, v) for k, v in job.items() if k != "_contract"))
            hit = own and ledger.verification_cache.get(job_id) == stamp
            if not hit:
                rows = verified_resume_rows(ledger, job)
                rows.close()
            page = [
                {"ordinal": row["ordinal"], "record": decode_json(row["value"])}
                for row in db.execute(
                    "SELECT ordinal,CASE WHEN "
                    "length(CAST(COALESCE(output_json,source_json) AS BLOB))<=? "
                    "THEN COALESCE(output_json,source_json) ELSE NULL END AS value "
                    "FROM stream_rows "
                    "WHERE job_id=? AND ordinal>? ORDER BY ordinal LIMIT ?",
                    (job["_contract"]["limits"]["max_record_bytes"], job_id, after, limit),
                )
            ]
        except (sqlite3.Error, ValueError, TypeError) as error:
            raise StreamError("Cannot read verified streaming records") from error
        finally:
            if own:
                db.rollback()
        after_revision = (db.execute("PRAGMA data_version").fetchone()[0], db.total_changes)
        if not own:
            return page
        if before != after_revision:
            ledger.verification_cache.pop(job_id, None)
            continue
        ledger.verification_cache[job_id] = stamp
        ledger.verification_cache.move_to_end(job_id)
        while len(ledger.verification_cache) > 32:
            ledger.verification_cache.popitem(last=False)
        return page
    raise StreamError("Streaming ledger changed during paging; retry from a stable revision")
