# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Private project JSON cache with atomic bounded writes and explicit expiry.

Cached assessments remain untrusted model responses. The research caller must
validate and ground every reused response against its newly captured source.
The main SQLite file is capped; DELETE-mode rollback journals can temporarily
occupy additional disk space up to approximately another database-sized copy.
Directory ownership is an operating-system boundary, not enterprise RBAC.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from verboisy.cache_policy import CachePolicy, is_cache_integer
from verboisy.utils.json_payload import decode_json

APPLICATION_ID = 0x56424331


class CacheError(ValueError):
    """The optional cache cannot be safely read or updated."""


@dataclass(frozen=True)
class CacheLookup:
    state: Literal["hit", "miss", "expired", "corrupt"]
    payload: dict[str, Any] | None = None
    age_seconds: float | None = None


def _encode(value: dict[str, Any]) -> bytes:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    pending: list[Any] = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if any(not isinstance(key, str) for key in node):
                raise ValueError("Cache object keys must be strings")
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, tuple):
            raise ValueError("Cache arrays must be JSON lists")
    return raw


def _decode(raw: bytes) -> dict[str, Any]:
    value = decode_json(raw)
    if not isinstance(value, dict):
        raise ValueError("Cache payload must be an object")
    return value


def _key(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CacheError("Cache keys must be SHA-256 fingerprints")


def _private(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    if path.is_symlink() or not (
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    ):
        raise CacheError("Cache paths must be real directories and regular files")
    if not directory and info.st_nlink != 1:
        raise CacheError("Hard-linked cache files are not supported")
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise CacheError("Cache directory/files must be private to their operating-system owner")


class ProjectCache:
    """One short-lived connection; independent processes coordinate through SQLite."""

    def __init__(self, policy: CachePolicy):
        self.policy = policy
        self.connection: sqlite3.Connection | None = None
        created = False
        try:
            root = policy.directory
            if root.is_symlink():
                raise CacheError("Linked cache directories are not supported")
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            _private(root, directory=True)
            path = policy.database
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            except FileExistsError:
                _private(path, directory=False)
                with path.open("rb") as stream:
                    header = stream.read(100)
                if (
                    len(header) != 100
                    or header[:16] != b"SQLite format 3\x00"
                    or int.from_bytes(header[68:72], "big") != APPLICATION_ID
                ):
                    raise CacheError("Existing file is not a Verboisy project cache") from None
            else:
                os.close(descriptor)
                created = True
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    _private(sidecar, directory=False)
            db = sqlite3.connect(path, timeout=0.25, isolation_level=None)
            self.connection = db
            if created:
                db.execute("PRAGMA page_size=4096")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA cache_size=-1024")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            pages = db.execute(f"PRAGMA max_page_count={policy.max_bytes // page_size}").fetchone()[
                0
            ]
            if pages > policy.max_bytes // page_size:
                raise CacheError(
                    "Existing cache exceeds this disk limit; clear it using its previous limit"
                )
            if created:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    db.execute("PRAGMA user_version=1")
                    db.execute(
                        "CREATE TABLE project(scope TEXT NOT NULL,entries INTEGER NOT NULL,"
                        "payload_bytes INTEGER NOT NULL)"
                    )
                    db.execute("INSERT INTO project VALUES(?,0,0)", (policy.scope,))
                    db.execute(
                        "CREATE TABLE entries(key TEXT PRIMARY KEY,payload BLOB NOT NULL,"
                        "digest TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL,"
                        "accessed INTEGER NOT NULL) WITHOUT ROWID"
                    )
                    db.execute("CREATE INDEX eviction ON entries(accessed,key)")
                    db.execute(
                        "CREATE TRIGGER entry_added AFTER INSERT ON entries BEGIN "
                        "UPDATE project SET entries=entries+1,"
                        "payload_bytes=payload_bytes+length(new.payload); END"
                    )
                    db.execute(
                        "CREATE TRIGGER entry_removed AFTER DELETE ON entries BEGIN "
                        "UPDATE project SET entries=entries-1,"
                        "payload_bytes=payload_bytes-length(old.payload); END"
                    )
                    db.execute(
                        "CREATE TRIGGER entry_changed AFTER UPDATE OF payload ON entries BEGIN "
                        "UPDATE project SET payload_bytes=payload_bytes+length(new.payload)"
                        "-length(old.payload); END"
                    )
                    db.execute(
                        "CREATE TABLE counters(name TEXT PRIMARY KEY,"
                        "value INTEGER NOT NULL) WITHOUT ROWID"
                    )
            if db.execute("PRAGMA user_version").fetchone()[0] != 1 or db.execute(
                "SELECT scope FROM project"
            ).fetchall() != [(policy.scope,)]:
                raise CacheError("Cache version or project scope differs")
            count, size = db.execute("SELECT entries,payload_bytes FROM project").fetchone()
            if not is_cache_integer(count) or not is_cache_integer(size) or count < 0 or size < 0:
                raise CacheError("Cache accounting is malformed")
        except (OSError, sqlite3.Error, CacheError) as error:
            self.close()
            if created:
                with suppress(OSError):
                    policy.database.unlink(missing_ok=True)
            raise CacheError("Project cache unavailable or incompatible") from error

    def _db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise CacheError("Project cache is closed")
        return self.connection

    def _count(self, name: str, amount: int = 1) -> None:
        self._db().execute(
            "INSERT INTO counters VALUES(?,?) ON CONFLICT(name) DO UPDATE "
            "SET value=value+excluded.value",
            (name, amount),
        )

    def _digest(self, key: str, raw: bytes, created: int, expires: int) -> str:
        context = f"{self.policy.scope}\x00{key}\x00{created}:{expires}\x00".encode()
        return hashlib.sha256(context + raw).hexdigest()

    def get(self, key: str) -> CacheLookup:
        _key(key)
        now = time.time_ns()
        db = self._db()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT payload,digest,created,expires FROM entries WHERE key=?", (key,)
                ).fetchone()
                if row is None:
                    self._count("misses")
                    return CacheLookup("miss")
                raw, digest, created, expires = row
                if (
                    not is_cache_integer(created)
                    or not is_cache_integer(expires)
                    or not created
                    <= now
                    < min(expires, created + self.policy.ttl_seconds * 1_000_000_000)
                ):
                    db.execute("DELETE FROM entries WHERE key=?", (key,))
                    self._count("expired")
                    return CacheLookup("expired")
                try:
                    if not isinstance(raw, bytes) or len(raw) > self.policy.max_entry_bytes:
                        raise ValueError("Invalid cache payload size")
                    if self._digest(key, raw, created, expires) != digest:
                        raise ValueError("Cache payload hash differs")
                    payload = _decode(raw)
                except (ValueError, UnicodeError, TypeError):
                    db.execute("DELETE FROM entries WHERE key=?", (key,))
                    self._count("corrupt")
                    return CacheLookup("corrupt")
                db.execute("UPDATE entries SET accessed=? WHERE key=?", (now, key))
                self._count("hits")
                return CacheLookup("hit", payload, (now - created) / 1_000_000_000)
        except sqlite3.Error as error:
            raise CacheError("Project cache lookup failed") from error

    def put(self, key: str, payload: dict[str, Any]) -> bool:
        _key(key)
        if not isinstance(payload, dict):
            raise CacheError("Cache payload must be a JSON object")
        try:
            raw = _encode(payload)
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise CacheError("Cache payload must be strict JSON") from error
        if len(raw) > self.policy.max_entry_bytes:
            return False
        now = time.time_ns()
        db = self._db()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM entries WHERE key=?", (key,))
                count, size = db.execute("SELECT entries,payload_bytes FROM project").fetchone()
                evicted = 0
                while (
                    count >= self.policy.entry_limit or size + len(raw) > self.policy.max_bytes // 2
                ):
                    old = db.execute(
                        "SELECT key,length(payload) FROM entries ORDER BY accessed,key LIMIT 1"
                    ).fetchone()
                    db.execute("DELETE FROM entries WHERE key=?", (old[0],))
                    count, size, evicted = count - 1, size - old[1], evicted + 1
                expires = now + self.policy.ttl_seconds * 1_000_000_000
                db.execute(
                    "INSERT INTO entries VALUES(?,?,?,?,?,?)",
                    (key, raw, self._digest(key, raw, now, expires), now, expires, now),
                )
                self._count("writes")
                self._count("evictions", evicted)
            return True
        except sqlite3.Error as error:
            raise CacheError("Project cache write failed; previous transaction retained") from error

    def stats(self) -> dict[str, Any]:
        db = self._db()
        try:
            count, size = db.execute("SELECT entries,payload_bytes FROM project").fetchone()
            return {
                "entries": count,
                "payload_bytes": size,
                "database_bytes": self.policy.database.stat().st_size,
                "max_database_bytes": self.policy.max_bytes,
                "max_entries": self.policy.entry_limit,
                "ttl_seconds": self.policy.ttl_seconds,
                "counters": dict(db.execute("SELECT name,value FROM counters")),
            }
        except (sqlite3.Error, OSError) as error:
            raise CacheError("Project cache statistics unavailable") from error

    def clear(self) -> None:
        db = self._db()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM entries")
                db.execute("DELETE FROM counters")
            db.execute("VACUUM")
        except sqlite3.Error as error:
            raise CacheError("Project cache clear failed") from error

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> ProjectCache:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
