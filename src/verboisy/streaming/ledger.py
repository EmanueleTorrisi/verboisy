# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Separate versioned ledger: immutable byte chunks and row/checkpoint transactions."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from verboisy.streaming.contract import CHUNK_BYTES, StreamError


class StreamLedger:
    def __init__(
        self, path: Path, *, max_storage_bytes: int = 17_179_869_184, read_only: bool = False
    ):
        if (
            isinstance(max_storage_bytes, bool)
            or not isinstance(max_storage_bytes, int)
            or max_storage_bytes < 65_536
        ):
            raise StreamError("Streaming storage limit must allow at least 64 KiB")
        if path.is_symlink():
            raise StreamError("Streaming ledger must not be a symlink")
        self.path = path.resolve()
        self.lock = FileLock(str(self.path) + ".lock")
        self.db: sqlite3.Connection | None = None
        try:
            if read_only:
                if not self.path.is_file():
                    raise StreamError("Choose an existing streaming ledger")
                db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            else:
                self.lock.acquire(timeout=0)
                db = sqlite3.connect(self.path)
            self.db = db
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA cache_size=-8192")
            db.execute("PRAGMA mmap_size=0")
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if tables:
                if "stream_meta" not in tables:
                    raise StreamError("Not a streaming ledger")
                versions = db.execute("SELECT version FROM stream_meta").fetchall()
                if len(versions) != 1 or versions[0][0] != 1:
                    raise StreamError("Unsupported streaming ledger version")
            elif read_only:
                raise StreamError("Not a streaming ledger")
            else:
                db.executescript("""
                    CREATE TABLE stream_meta(version INTEGER NOT NULL);
                    INSERT INTO stream_meta VALUES(1);
                    CREATE TABLE stream_jobs(
                        id TEXT PRIMARY KEY, contract TEXT NOT NULL, status TEXT NOT NULL,
                        captured INTEGER NOT NULL DEFAULT 0, byte_count INTEGER NOT NULL DEFAULT 0,
                        sha256 TEXT, processed INTEGER NOT NULL DEFAULT 0, reason TEXT);
                    CREATE TABLE stream_chunks(
                        job_id TEXT NOT NULL REFERENCES stream_jobs(id), seq INTEGER NOT NULL,
                        sha256 TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(job_id,seq));
                    CREATE TABLE stream_rows(
                        job_id TEXT NOT NULL REFERENCES stream_jobs(id), ordinal INTEGER NOT NULL,
                        first_line INTEGER, last_line INTEGER, source_json TEXT NOT NULL,
                        output_json TEXT, PRIMARY KEY(job_id,ordinal));
                """)
            if not read_only:
                db.execute("PRAGMA foreign_keys=ON")
                page_size = db.execute("PRAGMA page_size").fetchone()[0]
                if db.execute("PRAGMA page_count").fetchone()[0] * page_size > max_storage_bytes:
                    raise StreamError("Streaming ledger exceeds its storage limit")
                db.execute(f"PRAGMA max_page_count={max_storage_bytes // page_size}")
        except Timeout:
            self.close()
            raise StreamError("Streaming ledger is already in use") from None
        except (sqlite3.Error, OSError):
            self.close()
            raise StreamError("Cannot open streaming ledger") from None
        except BaseException:
            self.close()
            raise

    @property
    def connection(self) -> sqlite3.Connection:
        if self.db is None:
            raise StreamError("Streaming ledger is closed")
        return self.db

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM stream_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise StreamError("No saved streaming job found")
        return dict(row)

    def page(self, job_id: str, *, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if (
            isinstance(after, bool)
            or not isinstance(after, int)
            or after < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise StreamError("Page requires a nonnegative cursor and limit from 1 to 1000")
        self.job(job_id)
        return [
            {"ordinal": row["ordinal"], "record": json.loads(row["value"])}
            for row in self.connection.execute(
                "SELECT ordinal, COALESCE(output_json,source_json) AS value FROM stream_rows "
                "WHERE job_id=? AND ordinal>? ORDER BY ordinal LIMIT ?",
                (job_id, after, limit),
            )
        ]

    def jobs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Recover job IDs after process termination without loading row payloads."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StreamError("Job inventory limit must be from 1 to 1000")
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT id,status,captured,byte_count,sha256,processed,reason "
                "FROM stream_jobs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
        ]

    def close(self) -> None:
        try:
            if self.db is not None:
                self.db.close()
                self.db = None
        finally:
            self.lock.release()


class ChunkReader(io.RawIOBase):
    """Sequential byte view; each bounded chunk and the aggregate hash are checked."""

    def __init__(self, ledger: StreamLedger, job: dict[str, Any]):
        super().__init__()
        self.cursor = ledger.connection.execute(
            "SELECT seq,sha256,content FROM stream_chunks WHERE job_id=? ORDER BY seq", (job["id"],)
        )
        self.job = job
        self.pending = memoryview(b"")
        self.sequence = 0
        self.digest = hashlib.sha256()
        self.count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if not self.pending:
            row = self.cursor.fetchone()
            if row is None:
                if (
                    self.count != self.job["byte_count"]
                    or self.digest.hexdigest() != self.job["sha256"]
                ):
                    raise StreamError("Streaming source aggregate integrity failure")
                return 0
            content = row["content"]
            if (
                row["seq"] != self.sequence
                or not content
                or len(content) > CHUNK_BYTES
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise StreamError("Streaming source chunk integrity failure")
            self.sequence += 1
            self.digest.update(content)
            self.count += len(content)
            self.pending = memoryview(content)
        size = min(len(buffer), len(self.pending))
        buffer[:size] = self.pending[:size]
        self.pending = self.pending[size:]
        return size
