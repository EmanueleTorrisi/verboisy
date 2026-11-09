# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Write a verified snapshot delta using a disposable, bounded SQLite index."""

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO

from verboisy.streaming.contract import StreamError

_PAGE_BYTES = 4096
_COMMIT_ROWS = 4096
_KEY_BYTES = 4096


@dataclass(frozen=True)
class UpdateLimits:
    """Separate ceilings for the temporary index and complete update file."""

    index_bytes: int = 4 * 1024**3
    output_bytes: int = 8 * 1024**3

    def __post_init__(self) -> None:
        for value, minimum in ((self.index_bytes, 65536), (self.output_bytes, 1)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise StreamError("Updates require at least 64 KiB of index and one output byte")


@dataclass(frozen=True)
class UpdateResult:
    output: str
    inserted: int
    updated: int
    removed: int
    unchanged: int
    unobserved: int
    body_sha256: str


@dataclass(frozen=True)
class _Record:
    ordinal: int
    first_line: int | None
    last_line: int | None
    value: dict[str, Any]


@dataclass(frozen=True)
class _Version:
    job_id: str
    source_sha256: str
    count: int
    records: Iterable[_Record]

    def reference(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "source_sha256": self.source_sha256, "rows": self.count}


def _json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _key_paths(pointers: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if not isinstance(pointers, tuple) or not 1 <= len(pointers) <= 8:
        raise StreamError("Choose one to eight record key pointers")
    result = []
    for pointer in pointers:
        if (
            not isinstance(pointer, str)
            or not pointer.startswith("/")
            or len(pointer) > 1024
            or re.search(r"~(?![01])", pointer)
        ):
            raise StreamError("Record keys must be non-root JSON pointers to object fields")
        parts = tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))
        if parts in result:
            raise StreamError("Record key pointers must be distinct")
        result.append(parts)
    return tuple(result)


def _record_key(record: _Record, paths: tuple[tuple[str, ...], ...]) -> bytes:
    values: list[str | int] = []
    for parts in paths:
        value: Any = record.value
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise StreamError(f"Missing record key at row {record.ordinal}")
            value = value[part]
        if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
            raise StreamError(
                f"Record key at row {record.ordinal} must be a nonempty string or integer"
            )
        if isinstance(value, str) and len(value) > _KEY_BYTES:
            raise StreamError(f"Record key at row {record.ordinal} exceeds 4096 encoded bytes")
        values.append(value)
    encoded = _json(values)
    if len(encoded) > _KEY_BYTES:
        raise StreamError(f"Record key at row {record.ordinal} exceeds 4096 encoded bytes")
    return encoded


class _Writer:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.written = 0
        self.digest = hashlib.sha256()

    def line(self, value: dict[str, Any], record: bytes | None = None) -> None:
        # Emit the already hashed record without encoding or buffering it again.
        prefix = _json(value)
        pieces = (prefix, b"\n") if record is None else (prefix[:-1], b',"row":', record, b"}\n")
        self.written += sum(map(len, pieces))
        if self.written > self.limit:
            raise StreamError("Streaming update exceeds its output byte limit")
        for piece in pieces:
            self.stream.write(piece)
            self.digest.update(piece)


def _index(db: sqlite3.Connection, limit: int) -> None:
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA page_size={_PAGE_BYTES}")
    db.execute(f"PRAGMA max_page_count={limit // _PAGE_BYTES}")
    db.execute("PRAGMA cache_size=-4096")
    # This private index is never reopened; only the completed update is published.
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute(
        "CREATE TABLE keys(key BLOB PRIMARY KEY,digest BLOB,ordinal INTEGER,first_line INTEGER,"
        "last_line INTEGER,seen INTEGER NOT NULL) WITHOUT ROWID"
    )


def _baseline(
    db: sqlite3.Connection, version: _Version, paths: tuple[tuple[str, ...], ...]
) -> None:
    count = 0
    for count, record in enumerate(version.records, 1):
        added = db.execute(
            "INSERT INTO keys VALUES(?,?,?,?,?,0) ON CONFLICT(key) DO NOTHING",
            (
                _record_key(record, paths),
                hashlib.sha256(_json(record.value)).digest(),
                record.ordinal,
                record.first_line,
                record.last_line,
            ),
        )
        if added.rowcount != 1:
            raise StreamError(f"Duplicate baseline key at row {record.ordinal}")
        if count % _COMMIT_ROWS == 0:
            db.commit()
    if count != version.count:
        raise StreamError("Baseline replay did not reach its declared row count")
    db.commit()


def _proof(
    ordinal: int, first_line: int | None, last_line: int | None, digest: bytes
) -> dict[str, Any]:
    return {
        "ordinal": ordinal,
        "first_line": first_line,
        "last_line": last_line,
        "row_sha256": digest.hex(),
    }


def _prior(row: sqlite3.Row) -> dict[str, Any]:
    return _proof(row["ordinal"], row["first_line"], row["last_line"], row["digest"])


def _current(
    db: sqlite3.Connection,
    version: _Version,
    paths: tuple[tuple[str, ...], ...],
    writer: _Writer,
) -> tuple[int, int, int]:
    inserted = updated = unchanged = count = 0
    for count, record in enumerate(version.records, 1):
        key = _record_key(record, paths)
        prior = db.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
        encoded = _json(record.value)
        digest = hashlib.sha256(encoded).digest()
        if prior is None:
            db.execute("INSERT INTO keys(key,seen) VALUES(?,1)", (key,))
        else:
            if prior["seen"]:
                raise StreamError(f"Duplicate current key at row {record.ordinal}")
            db.execute("UPDATE keys SET seen=1 WHERE key=?", (key,))
        if prior is not None and prior["digest"] == digest:
            unchanged += 1
        else:
            event = {
                "kind": "change",
                "op": "insert" if prior is None else "update",
                "key": json.loads(key),
                "after": _proof(record.ordinal, record.first_line, record.last_line, digest),
            }
            if prior is None:
                inserted += 1
            else:
                updated += 1
                event["before"] = _prior(prior)
            writer.line(event, encoded)
        if count % _COMMIT_ROWS == 0:
            db.commit()
    if count != version.count:
        raise StreamError("Current replay did not reach its declared row count")
    db.commit()
    return inserted, updated, unchanged


def _write_delta(
    baseline: _Version,
    current: _Version,
    *,
    keys: tuple[str, ...],
    contract_sha256: str,
    output: Path,
    complete_snapshot: bool,
    limits: UpdateLimits,
) -> UpdateResult:
    paths = _key_paths(keys)
    try:
        with TemporaryDirectory(
            prefix=".verboisy-update-", dir=output.parent, ignore_cleanup_errors=True
        ) as scratch:
            staged = Path(scratch) / "updates.jsonl"
            with closing(sqlite3.connect(Path(scratch) / "index.db")) as db:
                _index(db, limits.index_bytes)
                _baseline(db, baseline, paths)
                fd = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    writer = _Writer(stream, limits.output_bytes)
                    writer.line(
                        {
                            "kind": "manifest",
                            "version": "stream-update-1",
                            "key_pointers": keys,
                            "row_digest": "sha256-sorted-utf8-json-v1",
                            "baseline": baseline.reference(),
                            "current": current.reference(),
                            "contract_sha256": contract_sha256,
                            "complete_snapshot": complete_snapshot,
                        }
                    )
                    inserted, updated, unchanged = _current(db, current, paths, writer)
                    absent = baseline.count - updated - unchanged
                    if complete_snapshot:
                        for row in db.execute("SELECT * FROM keys WHERE seen=0 ORDER BY key"):
                            writer.line(
                                {
                                    "kind": "change",
                                    "op": "delete",
                                    "key": json.loads(row["key"]),
                                    "before": _prior(row),
                                }
                            )
                    result = UpdateResult(
                        str(output),
                        inserted,
                        updated,
                        absent if complete_snapshot else 0,
                        unchanged,
                        0 if complete_snapshot else absent,
                        writer.digest.hexdigest(),
                    )
                    summary = asdict(result)
                    del summary["output"]
                    writer.line({"kind": "summary", **summary})
                    stream.flush()
                    os.fsync(stream.fileno())
            # A same-directory hard link publishes the whole file without overwriting.
            os.link(staged, output)
    except sqlite3.Error as error:
        raise StreamError(
            "Cannot complete the streaming update index within its storage limit"
        ) from error
    except OSError as error:
        raise StreamError(
            "Cannot publish streaming update; choose a new path on a filesystem with hard links"
        ) from error
    return result
