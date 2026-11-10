# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validate the current streaming ledger layout without opening or changing it."""

import sqlite3

from verboisy.streaming.contract import StreamError


def validate_stream_ledger(db: sqlite3.Connection) -> None:
    if (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stream_meta'"
        ).fetchone()
        is None
    ):
        raise StreamError("Not a streaming ledger")
    versions = db.execute("SELECT version FROM stream_meta LIMIT 2").fetchall()
    if len(versions) != 1 or versions[0][0] != 1:
        raise StreamError("Unsupported streaming ledger version")
    required = {
        "stream_meta": {"version"},
        "stream_jobs": {
            "id",
            "contract",
            "status",
            "captured",
            "byte_count",
            "sha256",
            "processed",
            "reason",
        },
        "stream_chunks": {"job_id", "seq", "sha256", "content"},
        "stream_rows": {
            "job_id",
            "ordinal",
            "first_line",
            "last_line",
            "source_json",
            "output_json",
        },
    }
    for table, columns in required.items():
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        if not columns <= {row[1] for row in info}:
            raise StreamError("Incomplete streaming ledger schema")
        expected_key = {
            "stream_rows": {"job_id": 1, "ordinal": 2},
            "stream_chunks": {"job_id": 1, "seq": 2},
            "stream_jobs": {"id": 1},
        }.get(table)
        if expected_key and {row[1]: row[5] for row in info if row[5]} != expected_key:
            raise StreamError("Invalid streaming ledger primary key")
