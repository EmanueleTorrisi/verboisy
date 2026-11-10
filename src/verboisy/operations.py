# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read-only operations reports over existing Verboisy ledgers."""

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from verboisy.storage.ledger_schema import validate_ledger_identity
from verboisy.storage.operations_journal import JOURNAL_COUNTERS, summarize_journal
from verboisy.utils.exceptions import VerboisyError

REPORT_LIMIT = 100
MAX_REPORT_LIMIT = 500
STATUSES = ("RUNNING", "PAUSED", "COMPLETED", "EXHAUSTED", "FAILED", "UNKNOWN")
STOP_REASONS = frozenset(
    {
        "coverage_or_identity_gaps",
        "dataset_asset_integrity",
        "dataset_consistency_gaps",
        "dataset_row_gaps",
        "dataset_source_budget",
        "dataset_source_failure",
        "initial_discovery",
        "interrupted",
        "invocation_row_budget",
        "model_request_budget",
        "observed_scope_exhausted",
        "page_budget",
        "proposed_changes",
        "provider_rate_limit",
        "run_timeout",
        "running",
        "search_request_budget",
        "source_failures",
        "storage_error",
        "target_met",
    }
)
_RESEARCH_TABLES = (
    ("accepted_records", "records", ""),
    ("rejected_candidates", "candidates", " AND accepted=0"),
    ("snapshots", "snapshots", ""),
    ("captured_assets", "dataset_assets", ""),
    ("identity_conflicts", "conflicts", ""),
)
RESEARCH_COUNTERS = (
    *(name for name, _, _ in _RESEARCH_TABLES),
    "coverage_gap_events",
    "reserved_request_units",
    "provider_reported_tokens",
)
STREAM_COUNTERS = ("processed_rows", "captured_bytes", "completed_captures")
PAGE_OUTCOMES = ("queued", "deferred", "repair", "active", "done", "blocked", "failed", "other")
_IDENTITY_COLUMNS = (
    "substr(id,1,37) AS id,substr(status,1,32) AS status,substr(reason,1,64) AS reason"
)


def operational_report(
    database: Path,
    *,
    kind: str = "research",
    run_id: str | None = None,
    limit: int = REPORT_LIMIT,
) -> dict[str, Any]:
    """Read one coherent snapshot of saved metadata, without replaying any input.

    The selection is either a single ID or the newest saved runs by ledger order.
    Report counters describe only that selection. Search and cache totals are
    unavailable if their selected journal exceeds the reporting bounds or is
    malformed. Reported tokens and reserved units are local accounting only.
    """
    if kind not in ("research", "stream"):
        raise VerboisyError("Choose a research or stream operations report")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_REPORT_LIMIT:
        raise VerboisyError("Operations report limit must be an integer from 1 to 500")
    if run_id is not None:
        _run_id(run_id)
    if database.is_symlink() or not database.is_file():
        raise VerboisyError("Choose an existing Verboisy ledger for the operations report")

    counters: tuple[str, ...]
    try:
        if kind == "stream":
            from verboisy.streaming.ledger import StreamLedger

            with closing(StreamLedger(database, read_only=True)) as ledger:
                ledger.connection.execute("PRAGMA query_only=ON")
                ledger.connection.execute("BEGIN")
                runs, truncated = _stream_runs(ledger.connection, run_id, limit)
            counters = STREAM_COUNTERS
            journal_state = "not_applicable"
        else:
            uri = database.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA cache_size=-8192")
                db.execute("PRAGMA mmap_size=0")
                db.execute("PRAGMA temp_store=FILE")
                db.execute("BEGIN")
                _research_schema(db)
                runs, truncated, journal_state = _research_runs(db, run_id, limit)
            counters = RESEARCH_COUNTERS
    except sqlite3.Error:
        raise VerboisyError("Cannot read the selected Verboisy ledger for reporting") from None

    statuses = dict.fromkeys(STATUSES, 0)
    reasons: Counter[str] = Counter()
    for run in runs:
        statuses[run["status"]] += 1
        reasons[run["stop_reason"] or "not_recorded"] += 1
    return {
        "report_version": "operations-1",
        "ledger_kind": kind,
        "scope": "selected_saved_ledger_metadata",
        "selection": {
            "run_id": run_id,
            "limit": 1 if run_id is not None else limit,
            "truncated": truncated,
        },
        "run_count": len(runs),
        "status_counts": statuses,
        "stop_reason_counts": dict(sorted(reasons.items())),
        "totals": {key: sum(run["counts"][key] for run in runs) for key in counters},
        "journal_state": journal_state,
        "journal_totals": (
            {key: sum(run["journal"][key] for run in runs) for key in JOURNAL_COUNTERS}
            if journal_state == "complete"
            else None
        ),
        "billing_recorded": False,
        "source_evidence_replayed": False,
        "runs": runs,
    }


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or len(value) not in (32, 36):
        raise VerboisyError("Expected a saved Verboisy run or job ID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise VerboisyError("Expected a saved Verboisy run or job ID") from None
    if value not in (parsed.hex, str(parsed)):
        raise VerboisyError("Expected a canonical saved Verboisy run or job ID")
    return value


def _count(value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise VerboisyError("Saved operational counters are invalid")
    return value


def _select(
    db: sqlite3.Connection, sql: str, run_id: str | None, limit: int
) -> tuple[list[sqlite3.Row], bool]:
    if run_id is not None:
        rows = db.execute(sql + " WHERE id=?", (run_id,)).fetchall()
        if len(rows) != 1:
            raise VerboisyError("No unique saved run or job found for this report")
        return rows, False
    rows = db.execute(sql + " ORDER BY rowid DESC LIMIT ?", (limit + 1,)).fetchall()
    return rows[:limit], len(rows) > limit


def _identity(row: sqlite3.Row) -> dict[str, Any]:
    status, reason = row["status"], row["reason"]
    return {
        "run_id": _run_id(row["id"]),
        "status": status if status in STATUSES else "UNKNOWN",
        "stop_reason": reason if reason is None or reason in STOP_REASONS else "other",
    }


def _stream_runs(
    db: sqlite3.Connection, run_id: str | None, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    rows, truncated = _select(
        db,
        f"SELECT {_IDENTITY_COLUMNS},captured,byte_count,processed FROM stream_jobs",
        run_id,
        limit,
    )
    runs: list[dict[str, Any]] = []
    for row in rows:
        captured = _count(row["captured"])
        if captured not in (0, 1):
            raise VerboisyError("Saved capture indicator is invalid")
        identity = _identity(row)
        processed, byte_count = _count(row["processed"]), _count(row["byte_count"])
        if not captured and (processed or byte_count or identity["status"] == "COMPLETED"):
            raise VerboisyError("Saved stream progress requires a completed capture")
        runs.append(
            {
                **identity,
                "counts": {
                    "processed_rows": processed,
                    "captured_bytes": byte_count,
                    "completed_captures": captured,
                },
            }
        )
    return runs, truncated


def _research_schema(db: sqlite3.Connection) -> None:
    versions = db.execute("SELECT version FROM research_meta LIMIT 2").fetchall()
    if len(versions) != 1 or versions[0][0] != 4:
        raise VerboisyError("Operations reporting requires a current research ledger")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    validate_ledger_identity(db, tables)


def _research_runs(
    db: sqlite3.Connection, run_id: str | None, limit: int
) -> tuple[list[dict[str, Any]], bool, str]:
    rows, truncated = _select(
        db, f"SELECT {_IDENTITY_COLUMNS},tokens,reserved FROM research_runs", run_id, limit
    )
    runs: list[dict[str, Any]] = []
    for row in rows:
        counts = dict.fromkeys(RESEARCH_COUNTERS, 0)
        counts["provider_reported_tokens"] = _count(row["tokens"])
        counts["reserved_request_units"] = _count(row["reserved"])
        runs.append(
            {
                **_identity(row),
                "counts": counts,
                "page_outcomes": dict.fromkeys(PAGE_OUTCOMES, 0),
                "journal_activity": {"first_event_at": None, "last_event_at": None},
            }
        )
    if not runs:
        return runs, truncated, "complete"

    by_id = {run["run_id"]: run for run in runs}
    ids = tuple(by_id)
    marks = ",".join("?" for _ in ids)
    where = f"run_id IN ({marks})"
    for metric, table, extra in _RESEARCH_TABLES:
        for rid, count in db.execute(
            f"SELECT run_id,COUNT(*) FROM {table} WHERE {where}{extra} GROUP BY run_id", ids
        ):
            by_id[rid]["counts"][metric] = count
    states = ",".join("?" for _ in PAGE_OUTCOMES)
    for rid, outcome, count in db.execute(
        f"SELECT run_id,CASE WHEN status IN ({states}) THEN status ELSE 'other' END AS outcome,"
        f" COUNT(*) FROM pages WHERE {where} GROUP BY 1,2",
        (*PAGE_OUTCOMES, *ids),
    ):
        by_id[rid]["page_outcomes"][outcome] = count
    for rid, gaps, first, last in db.execute(
        "SELECT run_id,SUM(CASE WHEN kind='coverage_gap' THEN 1 ELSE 0 END),"
        " MIN(substr(created_at,1,20)),MAX(substr(created_at,1,20)) "
        f"FROM events WHERE {where} GROUP BY run_id",
        ids,
    ):
        by_id[rid]["counts"]["coverage_gap_events"] = gaps
        by_id[rid]["journal_activity"] = {
            "first_event_at": _timestamp(first),
            "last_event_at": _timestamp(last),
        }
    journal_state, journal = summarize_journal(db, ids)
    for run in runs:
        run["journal"] = journal.get(run["run_id"])
    return runs, truncated, journal_state


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 19:
        return None
    try:
        stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return stamp.isoformat(timespec="seconds") + "Z"
