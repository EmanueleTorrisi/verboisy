# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Create and upgrade the research ledger without changing its version contract.

The store owns connection setup and cleanup. This module retains the existing
version checks, schema SQL and stable-ID backfill. Schema creation and supported
upgrades commit together; failures leave no partially published ledger schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from verboisy.utils.exceptions import VerboisyError


def validate_ledger_identity(db: sqlite3.Connection, tables: set[str]) -> None:
    """Reject foreign/partial databases before journal-mode changes or migration."""
    tables = {name for name in tables if not name.startswith("sqlite_")}
    if not tables:
        return
    required = {
        "research_meta": {"version"},
        "research_runs": {
            "id",
            "goal",
            "schema_json",
            "task_json",
            "status",
            "reason",
            "tokens",
            "reserved",
            "export_path",
        },
        "pages": {"id", "run_id", "url", "parent_url", "depth", "status", "reason"},
        "snapshots": {"id", "run_id", "page_id", "payload", "html", "visible_html"},
        "candidates": {"id", "run_id", "snapshot_id", "payload", "reasons", "accepted"},
        "records": {"id", "run_id", "identity", "payload", "candidate_id"},
        "conflicts": {"run_id", "identity"},
        "events": {"id", "run_id", "kind", "payload", "created_at"},
    }
    try:
        versions = db.execute("SELECT version FROM research_meta").fetchall()
        if len(versions) != 1 or versions[0][0] not in (2, 3, 4):
            raise VerboisyError("Unsupported research database version")
        version = versions[0][0]
        if version >= 3:
            required["records"].add("stable_id")
        if version >= 4:
            required.update(
                {
                    "dataset_blobs": {"sha256", "content"},
                    "dataset_assets": {"id", "run_id", "sha256", "metadata", "acquired_at"},
                }
            )
        allowed = set(required) | {"dataset_blobs", "dataset_assets"}
        if tables - allowed or not set(required) <= tables:
            raise VerboisyError(
                "Not a complete supported research ledger; preserve it and choose a new path"
            )
        for table, columns in required.items():
            if not columns <= {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                raise VerboisyError("Incomplete research ledger columns")
    except sqlite3.Error:
        raise VerboisyError(
            "Not a supported research ledger; preserve it and choose a new path"
        ) from None


def initialize_ledger(
    db: sqlite3.Connection,
    tables: set[str],
    *,
    current_version: int,
    stable_row_id: Callable[[str, str], str],
) -> None:
    """Apply the existing supported upgrades using the store's current ID helper."""
    validate_ledger_identity(db, tables)
    if "research_meta" in tables:
        rows = db.execute("SELECT version FROM research_meta").fetchall()
        # An arbitrary first row cannot establish an unambiguous upgrade path.
        version = rows[0][0] if len(rows) == 1 else None
        if version not in (2, 3, current_version):
            raise VerboisyError("Unsupported research database version")
    else:
        version = None

    # executescript commits any pending transaction before running its SQL. Begin
    # inside the script, then let the context include DDL, backfill and version
    # publication in one commit or rollback, including interruption failures.
    with db:
        _create_and_upgrade(db, version, current_version, stable_row_id)


def _create_and_upgrade(
    db: sqlite3.Connection,
    version: int | None,
    current_version: int,
    stable_row_id: Callable[[str, str], str],
) -> None:
    db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS research_meta(version INTEGER NOT NULL);
            INSERT INTO research_meta SELECT 4 WHERE NOT EXISTS(SELECT 1 FROM research_meta);
            CREATE TABLE IF NOT EXISTS research_runs(
              id TEXT PRIMARY KEY,
              goal TEXT,
              schema_json TEXT,
              task_json TEXT,
              status TEXT,
              reason TEXT,
              tokens INTEGER DEFAULT 0,
              reserved INTEGER DEFAULT 0,
              export_path TEXT
            );
            CREATE TABLE IF NOT EXISTS dataset_blobs(
              sha256 TEXT PRIMARY KEY,
              content BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dataset_assets(
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL REFERENCES research_runs(id),
              sha256 TEXT NOT NULL REFERENCES dataset_blobs(sha256),
              metadata TEXT NOT NULL,
              acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS pages(
              id INTEGER PRIMARY KEY,
              run_id TEXT REFERENCES research_runs(id),
              url TEXT,
              parent_url TEXT,
              depth INTEGER,
              status TEXT DEFAULT 'queued',
              reason TEXT,
              UNIQUE(run_id,url)
            );
            CREATE TABLE IF NOT EXISTS snapshots(
              id TEXT PRIMARY KEY,
              run_id TEXT REFERENCES research_runs(id),
              page_id INTEGER REFERENCES pages(id),
              payload TEXT,
              html TEXT,
              visible_html TEXT
            );
            CREATE TABLE IF NOT EXISTS candidates(
              id INTEGER PRIMARY KEY,
              run_id TEXT REFERENCES research_runs(id),
              snapshot_id TEXT REFERENCES snapshots(id),
              payload TEXT,
              reasons TEXT,
              accepted INTEGER
            );
            CREATE TABLE IF NOT EXISTS records(
              id INTEGER PRIMARY KEY,
              run_id TEXT REFERENCES research_runs(id),
              identity TEXT,
              stable_id TEXT,
              payload TEXT,
              candidate_id INTEGER REFERENCES candidates(id),
              UNIQUE(run_id,identity),
              UNIQUE(run_id,stable_id)
            );
            CREATE TABLE IF NOT EXISTS conflicts(
              run_id TEXT REFERENCES research_runs(id),
              identity TEXT,
              PRIMARY KEY(run_id,identity)
            );
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY,
              run_id TEXT REFERENCES research_runs(id),
              kind TEXT,
              payload TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
    if version == 2:
        columns = {row[1] for row in db.execute("PRAGMA table_info(records)").fetchall()}
        if "stable_id" not in columns:
            db.execute("ALTER TABLE records ADD COLUMN stable_id TEXT")
        rows = db.execute("SELECT id,run_id,identity FROM records").fetchall()
        for row in rows:
            db.execute(
                "UPDATE records SET stable_id=? WHERE id=?",
                (stable_row_id(row["run_id"], row["identity"]), row["id"]),
            )
        db.execute("UPDATE research_meta SET version=?", (current_version,))
    if version == 3:
        db.execute("UPDATE research_meta SET version=?", (current_version,))
