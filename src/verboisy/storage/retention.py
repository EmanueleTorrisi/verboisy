# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect and delete completed ledger entries in dependency order."""

import sqlite3
from uuid import UUID

from verboisy.storage.ledger_schema import validate_ledger_identity
from verboisy.streaming.ledger_schema import validate_stream_ledger
from verboisy.utils.exceptions import VerboisyError

RESEARCH_TABLES = (
    "records",
    "candidates",
    "snapshots",
    "pages",
    "conflicts",
    "events",
    "dataset_assets",
    "research_runs",
)
STREAM_TABLES = ("stream_rows", "stream_chunks", "stream_jobs")
_EVIDENCE_LINKS = (
    ("records", "candidate_id", "candidates"),
    ("candidates", "snapshot_id", "snapshots"),
    ("snapshots", "page_id", "pages"),
)


def canonical_id(value: str) -> str:
    """Keep the existing UUID spellings for research runs and stream jobs."""
    if not isinstance(value, str) or len(value) not in (32, 36):
        raise VerboisyError("Expected a saved Verboisy run or job ID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise VerboisyError("Expected a saved Verboisy run or job ID") from None
    if value not in (parsed.hex, str(parsed)):
        raise VerboisyError("Use canonical saved run and job IDs")
    return value


def _marks(values: tuple[str, ...]) -> str:
    return ",".join("?" for _ in values)


def select_completed(
    db: sqlite3.Connection,
    kind: str,
    keep_last: int,
    protected: tuple[str, ...],
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    """Protect the newest completed entries before selecting oldest deletions."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
        raise VerboisyError("Retention does not accept ledgers with triggers or views")
    tables = {
        name
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not name.startswith("sqlite_")
    }
    if kind == "research":
        if tables != {*RESEARCH_TABLES, "research_meta", "dataset_blobs"}:
            raise VerboisyError("Retention requires an unmodified current research ledger layout")
        if db.execute("SELECT version FROM research_meta LIMIT 2").fetchall() != [(4,)]:
            raise VerboisyError("Retention requires the current research ledger version")
        validate_ledger_identity(db, tables)
        table = "research_runs"
    else:
        if tables != {*STREAM_TABLES, "stream_meta"}:
            raise VerboisyError("Retention requires an unmodified current stream ledger layout")
        validate_stream_ledger(db)
        table = "stream_jobs"
    excluded = ""
    if protected:
        marks = _marks(protected)
        present = db.execute(f"SELECT id FROM {table} WHERE id IN ({marks})", protected).fetchall()
        if len(present) != len(protected):
            raise VerboisyError("A protected run or job ID does not exist in this ledger")
        excluded = f" AND id NOT IN ({marks})"
    rows = db.execute(
        f"SELECT id FROM {table} WHERE status='COMPLETED' AND rowid NOT IN ("
        f"SELECT rowid FROM {table} WHERE status='COMPLETED' ORDER BY rowid DESC LIMIT ?"
        f"){excluded} ORDER BY rowid LIMIT ?",
        (keep_last, *protected, limit + 1),
    ).fetchall()
    return tuple(canonical_id(row[0]) for row in rows[:limit]), len(rows) > limit


def _orphaned_blobs(marks: str) -> str:
    # A blob is eligible only if every current asset reference belongs to this plan.
    return (
        "SELECT b.sha256 FROM dataset_blobs AS b JOIN ("
        "SELECT sha256 FROM dataset_assets GROUP BY sha256 "
        f"HAVING SUM(CASE WHEN run_id IN ({marks}) THEN 0 ELSE 1 END)=0"
        ") AS owned ON owned.sha256=b.sha256"
    )


def _where(table: str, kind: str, marks: str) -> str:
    key = (
        "id"
        if table in ("research_runs", "stream_jobs")
        else ("run_id" if kind == "research" else "job_id")
    )
    return f"{key} IN ({marks})"


def _count(db: sqlite3.Connection, sql: str, ids: tuple[str, ...]) -> int:
    row = db.execute(sql, ids).fetchone()
    assert row is not None
    return int(row[0])


def planned_counts(db: sqlite3.Connection, kind: str, ids: tuple[str, ...]) -> dict[str, int]:
    tables = RESEARCH_TABLES if kind == "research" else STREAM_TABLES
    counts = dict.fromkeys(tables, 0)
    if kind == "research":
        counts["dataset_blobs"] = 0
    if not ids:
        return counts
    marks = _marks(ids)
    if kind == "research":
        for child, pointer, parent in _EVIDENCE_LINKS:
            shared = db.execute(
                f"SELECT 1 FROM {child} AS c JOIN {parent} AS p ON p.id=c.{pointer} "
                f"WHERE c.run_id IS NOT p.run_id AND (c.run_id IN ({marks}) OR "
                f"p.run_id IN ({marks})) LIMIT 1",
                (*ids, *ids),
            ).fetchone()
            if shared is not None:
                raise VerboisyError("Selected research runs have cross-run evidence links")
        count_blobs = f"SELECT COUNT(*) FROM ({_orphaned_blobs(marks)})"
        counts["dataset_blobs"] = _count(db, count_blobs, ids)
    for table in tables:
        where = _where(table, kind, marks)
        counts[table] = _count(db, f"SELECT COUNT(*) FROM {table} WHERE {where}", ids)
    return counts


def delete_planned(
    db: sqlite3.Connection, kind: str, ids: tuple[str, ...], counts: dict[str, int]
) -> None:
    """The caller owns the write transaction and must roll back on any mismatch."""
    marks = _marks(ids)
    tables = RESEARCH_TABLES if kind == "research" else STREAM_TABLES
    if kind == "research":
        db.execute("CREATE TEMP TABLE retention_blobs(sha256 TEXT PRIMARY KEY) WITHOUT ROWID")
        db.execute("INSERT INTO temp.retention_blobs " + _orphaned_blobs(marks), ids)
    previous = db.total_changes
    for table in tables:
        where = _where(table, kind, marks)
        if db.execute(f"DELETE FROM {table} WHERE {where}", ids).rowcount != counts[table]:
            raise VerboisyError("Retention deletion differs from its planned rows")
    if (
        kind == "research"
        and db.execute(
            "DELETE FROM dataset_blobs WHERE sha256 IN (SELECT sha256 FROM temp.retention_blobs)"
        ).rowcount
        != counts["dataset_blobs"]
    ):
        raise VerboisyError("Retention blob deletion differs from its plan")
    if db.total_changes - previous != sum(counts.values()):
        raise VerboisyError("Retention detected changes outside its approved rows")
