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


def initialize_ledger(
    db: sqlite3.Connection,
    tables: set[str],
    *,
    current_version: int,
    stable_row_id: Callable[[str, str], str],
) -> None:
    """Apply the existing supported upgrades using the store's current ID helper."""
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
