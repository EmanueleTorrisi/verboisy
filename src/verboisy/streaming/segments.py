# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepare successive sealed JSONL segments under one saved schema."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import uuid
from collections.abc import Generator, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, BinaryIO, TypedDict, TypeGuard

from filelock import FileLock, Timeout
from pydantic_settings import PydanticBaseSettingsSource, SettingsConfigDict

from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.storage.exporters import sync_directory
from verboisy.streaming.api import stream_dataset
from verboisy.streaming.contract import StreamError, StreamLimits, validate_stream_schema
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import ExtractionError
from verboisy.utils.json_payload import decode_json

_MIB = 1_048_576
_MAX_BYTES = 16 * _MIB
_FILE_NAMES = (
    "rows.jsonl",
    "rows.jsonl.evidence.jsonl",
    "rows.jsonl.source.bin",
    "rows.jsonl.manifest.json",
)
_APP_ID = 0x56534A31
_RECEIPT_BYTES = 8_192
_HASH = re.compile("[0-9a-f]{64}")
_STAGE = re.compile(r"\.stage-[0-9a-f]{32}")
_DIR_MARKER = ".format"
_DIR_MAGIC = b"verboisy sealed JSONL staging 1\n"
_DDL = """
    CREATE TABLE contract (value BLOB NOT NULL);
    CREATE TABLE segments (
        sequence INTEGER PRIMARY KEY CHECK(sequence > 0),
        source_sha256 TEXT NOT NULL,
        receipt BLOB NOT NULL
    );
"""


@dataclass(frozen=True)
class SealedJSONL:
    """A numbered immutable input; its SHA-256 must come from the producer."""

    sequence: int
    path: Path
    sha256: str


@dataclass(frozen=True)
class JSONLSegmentResult:
    """A newly committed or reverified bundle and its receipt digest."""

    sequence: int
    source_sha256: str
    receipt_sha256: str
    source_bytes: int
    rows: int
    directory: Path
    reused: bool


class _FileInfo(TypedDict):
    bytes: int
    sha256: str


@dataclass(frozen=True)
class _Prepared:
    receipt: bytes
    source_bytes: int
    rows: int


class _LocalSettings(Settings):
    # A local segment should not depend on provider credentials or a caller's
    # configured project cache. The only admitted input is its private copy.
    model_config = SettingsConfigDict(env_file=None)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[Any],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise StreamError(message)


def _integer(value: object) -> TypeGuard[int]:
    """Admit integer counters without treating a boolean as a count."""
    return isinstance(value, int) and not isinstance(value, bool)


def _lstat(path: Path) -> os.stat_result:
    return path.lstat()


def _entry_stat(entry: os.DirEntry[str]) -> os.stat_result:
    return entry.stat(follow_symlinks=False)


def _json(value: Any) -> bytes:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )
    return (text + "\n").encode()


def _uid() -> int:
    getter = getattr(os, "geteuid", None)
    if sys.platform != "linux" or not callable(getter):
        raise StreamError("Sealed JSONL workspaces require Linux or WSL")
    return int(getter())


def _workspace(path: Path) -> Path:
    uid = _uid()
    root = path.absolute()
    for parent in reversed(root.parents):
        info = _lstat(parent)
        _require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid in (0, uid)
            and not (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX),
            "The sealed JSONL workspace has an unsafe ancestor",
        )
    _require(root.resolve(strict=True) == root, "Use a canonical workspace path without links")
    _require(_private_dir(root), "Use an existing owner-only workspace with mode 0700")
    return root


def _regular(path: Path, *, owned: bool) -> os.stat_result:
    info = _lstat(path)
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and (not owned or (info.st_uid == _uid() and not info.st_mode & 0o022)),
        "Sealed JSONL files must be unlinked regular files",
    )
    return info


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _opened(path: Path, *, ceiling: int, owned: bool) -> Iterator[tuple[BinaryIO, int]]:
    before = _regular(path, owned=owned)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        _require(
            stat.S_ISREG(opened.st_mode)
            and opened.st_nlink == 1
            and _stamp(opened) == _stamp(before),
            "A sealed JSONL file changed before reading",
        )
        _require(0 <= opened.st_size <= ceiling, "A sealed JSONL file exceeds its byte limit")
        yield source, opened.st_size
        _require(
            _stamp(os.fstat(source.fileno())) == _stamp(opened)
            and _stamp(_regular(path, owned=owned)) == _stamp(opened),
            "A sealed JSONL file changed during reading",
        )


def _file_info(path: Path, ceiling: int) -> _FileInfo:
    with _opened(path, ceiling=ceiling, owned=True) as (stream, size):
        checksum = hashlib.sha256()
        remaining = size
        while block := stream.read(min(65_536, remaining + 1)):
            remaining -= len(block)
            _require(remaining >= 0, "A sealed JSONL output grew while reading")
            checksum.update(block)
        _require(remaining == 0, "A sealed JSONL output ended early")
    return {"bytes": size, "sha256": checksum.hexdigest()}


def _read(path: Path, ceiling: int) -> bytes:
    with _opened(path, ceiling=ceiling, owned=True) as (stream, size):
        data = stream.read(size + 1)
        _require(len(data) == size, "A sealed JSONL receipt changed while reading")
    return data


@contextmanager
def _catalog(root: Path, contract: bytes) -> Iterator[sqlite3.Connection]:
    lock_path = root / ".segments.lock"
    with suppress(FileNotFoundError):
        info = _regular(lock_path, owned=True)
        _require(info.st_size == 0, "The segment lock path contains data")
    try:
        with FileLock(str(lock_path), timeout=0):
            path = root / "segments.db"
            for suffix in ("", "-journal", "-wal", "-shm"):
                with suppress(FileNotFoundError):
                    _regular(root / (path.name + suffix), owned=True)
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                db.execute("PRAGMA cache_size=-2048")
                # An empty database can survive a stop before schema commit.
                if path.stat().st_size == 0:
                    with db:
                        init = f"BEGIN IMMEDIATE; PRAGMA application_id={_APP_ID};"
                        db.executescript(init + _DDL)
                        db.execute("INSERT INTO contract VALUES (?)", (contract,))
                    sync_directory(root)
                _require(
                    db.execute("PRAGMA application_id").fetchone()[0] == _APP_ID,
                    "Choose a sealed JSONL catalog, not an unrelated database",
                )
                saved = db.execute(
                    "SELECT CASE WHEN length(value)<=65536 THEN value END FROM contract LIMIT 2"
                ).fetchall()
                _require(saved == [(contract,)], "The saved sealed JSONL contract differs")
                yield db
    except Timeout as error:
        raise StreamError("The sealed JSONL workspace is already in use") from error


def _mark_scratch(scratch: Path, root: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=".marker-", dir=scratch)
    marker_path = Path(name)
    try:
        with os.fdopen(fd, "wb") as marker:
            marker.write(_DIR_MAGIC)
            marker.flush()
            os.fsync(marker.fileno())
        marker_path.replace(scratch / _DIR_MARKER)
        sync_directory(scratch)
        sync_directory(root)
    finally:
        marker_path.unlink(missing_ok=True)


def _clean_stages(root: Path) -> Path:
    # Only the coordinator uses this directory and threads cannot outlive it.
    scratch = root / ".segment-staging"
    scratch.mkdir(mode=0o700, exist_ok=True)
    _require(_private_dir(scratch), "The segment staging directory is not private")
    marker = scratch / _DIR_MARKER
    if not marker.exists() and not marker.is_symlink():
        with os.scandir(scratch) as entries:
            for entry in entries:
                info = _entry_stat(entry)
                _require(
                    re.fullmatch(r"\.marker-[a-z0-9_]{8}", entry.name) is not None
                    and stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1
                    and info.st_uid == _uid()
                    and info.st_size <= len(_DIR_MAGIC),
                    "Choose a workspace with a sealed JSONL staging directory",
                )
                _require(
                    _DIR_MAGIC.startswith(_read(Path(entry.path), len(_DIR_MAGIC))),
                    "Invalid interrupted segment staging marker",
                )
                Path(entry.path).unlink()
        _mark_scratch(scratch, root)
    _require(
        _read(scratch / _DIR_MARKER, len(_DIR_MAGIC)) == _DIR_MAGIC,
        "Choose a workspace with a sealed JSONL staging directory",
    )
    with os.scandir(scratch) as entries:
        for entry in entries:
            if entry.name == _DIR_MARKER:
                continue
            _require(
                _STAGE.fullmatch(entry.name) is not None and _private_dir(Path(entry.path)),
                "Unexpected path in the segment staging directory",
            )
            shutil.rmtree(entry.path)
    sync_directory(scratch)
    return scratch


def _private_dir(path: Path) -> bool:
    info = _lstat(path)
    return (
        stat.S_ISDIR(info.st_mode) and info.st_uid == _uid() and stat.S_IMODE(info.st_mode) == 0o700
    )


def _target(root: Path, sequence: int) -> Path:
    return root / f"segment-{sequence:019d}"


def _check_segment(segment: SealedJSONL) -> None:
    _require(
        isinstance(segment, SealedJSONL)
        and _integer(segment.sequence)
        and 1 <= segment.sequence < 2**63
        and isinstance(segment.path, Path)
        and isinstance(segment.sha256, str)
        and _HASH.fullmatch(segment.sha256) is not None,
        "Use a positive segment number, source path and lowercase SHA-256",
    )


def _copy_input(segment: SealedJSONL, target: Path, ceiling: int) -> int:
    with (
        _opened(segment.path, ceiling=ceiling, owned=False) as (source, size),
        target.open("xb") as output,
    ):
        _require(size > 0, "A sealed JSONL segment cannot be empty")
        checksum = hashlib.sha256()
        remaining = size
        while block := source.read(min(65_536, remaining + 1)):
            remaining -= len(block)
            _require(remaining >= 0, "A sealed JSONL segment grew while reading")
            output.write(block)
            checksum.update(block)
        _require(
            remaining == 0 and checksum.hexdigest() == segment.sha256,
            "The sealed JSONL source does not match its SHA-256",
        )
    return size


def _prepare(
    segment: SealedJSONL,
    stage: Path,
    schema: dict[str, Any],
    maximum: int,
    record_bytes: int,
    max_rows: int,
    ledger_bytes: int,
    contract_sha: str,
) -> _Prepared:
    source = stage / "input.jsonl"
    size = _copy_input(segment, source, maximum)
    bundle = stage / "bundle"
    bundle.mkdir(mode=0o700)
    result = stream_dataset(
        database=stage / "stream.db",
        source=source,
        dataset_format="jsonl",
        schema=schema,
        export=bundle / _FILE_NAMES[0],
        limits=StreamLimits(
            max_input_bytes=size,
            max_rows=min(size, max_rows),
            max_record_bytes=record_bytes,
            max_storage_bytes=ledger_bytes,
        ),
        config=_LocalSettings(dataset_local_roots=[str(stage)]),
    )
    _require(
        result.status == "COMPLETED"
        and result.source_sha256 == segment.sha256
        and result.input_bytes == size
        and 0 < result.processed_rows <= size,
        f"Sealed JSONL segment {segment.sequence} did not complete: "
        f"{result.reason or result.status}",
    )
    files = {name: _file_info(bundle / name, 4 * ledger_bytes) for name in _FILE_NAMES}
    _require(
        files[_FILE_NAMES[2]] == {"bytes": size, "sha256": segment.sha256},
        "The sealed JSONL bundle did not preserve source bytes",
    )
    receipt = _json(
        {
            "version": 1,
            "sequence": segment.sequence,
            "source_sha256": segment.sha256,
            "source_bytes": size,
            "rows": result.processed_rows,
            "files": files,
            "contract_sha256": contract_sha,
        }
    )
    with (bundle / "segment.json").open("xb") as stamp:
        stamp.write(receipt)
        stamp.flush()
        os.fsync(stamp.fileno())
    sync_directory(bundle)
    return _Prepared(receipt, size, result.processed_rows)


def _verify(
    directory: Path,
    receipt: bytes,
    segment: SealedJSONL,
    contract_sha: str,
    maximum: int,
    file_limit: int,
) -> JSONLSegmentResult:
    _require(_private_dir(directory), "A committed segment directory is not private")
    _require(
        _read(directory / "segment.json", _RECEIPT_BYTES) == receipt,
        "The saved segment receipt changed",
    )
    data = decode_json(receipt)
    _require(
        isinstance(data, dict)
        and data.get("version") == 1
        and data.get("sequence") == segment.sequence
        and data.get("source_sha256") == segment.sha256
        and data.get("contract_sha256") == contract_sha,
        "The saved segment identity differs",
    )
    size, rows, files = data.get("source_bytes"), data.get("rows"), data.get("files")
    _require(
        _integer(size)
        and _integer(rows)
        and 0 < rows <= size <= maximum
        and isinstance(files, dict)
        and set(files) == set(_FILE_NAMES)
        and files[_FILE_NAMES[2]] == {"bytes": size, "sha256": segment.sha256}
        and {entry.name for entry in directory.iterdir()} == {*_FILE_NAMES, "segment.json"},
        "The saved segment bundle is incomplete",
    )
    _require(
        all(_file_info(directory / name, file_limit) == files[name] for name in _FILE_NAMES),
        "A committed segment file changed",
    )
    return JSONLSegmentResult(
        segment.sequence,
        segment.sha256,
        hashlib.sha256(receipt).hexdigest(),
        size,
        rows,
        directory,
        True,
    )


def _recover_directory(target: Path, stage: Path, contract_sha: str) -> None:
    # A directory renamed before the catalog commit was not returned by the
    # API. Quarantine it inside the attempt before retrying that number.
    if target.exists() or target.is_symlink():
        _require(_private_dir(target), "Unexpected uncommitted segment directory")
        receipt = decode_json(_read(target / "segment.json", _RECEIPT_BYTES))
        _require(
            isinstance(receipt, dict)
            and receipt.get("version") == 1
            and receipt.get("contract_sha256") == contract_sha
            and _integer(receipt.get("sequence"))
            and _target(target.parent, receipt["sequence"]) == target
            and {entry.name for entry in target.iterdir()} == {*_FILE_NAMES, "segment.json"},
            "Unexpected uncommitted segment contents",
        )
        orphan = stage / "previous"
        target.rename(orphan)
        sync_directory(target.parent)
        sync_directory(stage)
        shutil.rmtree(orphan)


def _commit(
    db: sqlite3.Connection,
    target: Path,
    stage: Path,
    segment: SealedJSONL,
    receipt: bytes,
) -> None:
    bundle = stage / "bundle"
    _require(
        not target.exists() and not target.is_symlink(),
        "The next segment already has an output directory",
    )
    bundle.rename(target)
    sync_directory(target.parent)
    sync_directory(stage)
    with db:
        db.execute(
            "INSERT INTO segments VALUES (?, ?, ?)", (segment.sequence, segment.sha256, receipt)
        )


def _prepare_segments(
    segments: Iterable[SealedJSONL],
    root: Path,
    schema: dict[str, Any],
    contract: bytes,
    workers: int,
    maximum: int,
    record_bytes: int,
    max_rows: int,
) -> Generator[JSONLSegmentResult, None, None]:
    contract_sha = hashlib.sha256(contract).hexdigest()
    ledger_bytes = max(8 * _MIB, 4 * maximum)
    with _catalog(root, contract) as db:
        scratch = _clean_stages(root)
        highest = int(db.execute("SELECT COALESCE(MAX(sequence), 0) FROM segments").fetchone()[0])
        last = 0
        iterator = iter(segments)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while window := tuple(islice(iterator, workers)):
                cursor = highest
                for segment in window:
                    _check_segment(segment)
                    _require(
                        segment.sequence > last, "Segment numbers in a submission must increase"
                    )
                    last = segment.sequence
                    if segment.sequence > highest:
                        _require(
                            segment.sequence == cursor + 1, "New segment numbers must be contiguous"
                        )
                        _require(
                            not segment.path.resolve().is_relative_to(root),
                            "Place sealed source files outside the output workspace",
                        )
                        cursor = segment.sequence
                staged: dict[int, tuple[Path, Future[_Prepared]]] = {}
                paths: set[Path] = set()
                try:
                    for segment in window:
                        if segment.sequence <= highest:
                            continue
                        stage = scratch / (".stage-" + uuid.uuid4().hex)
                        stage.mkdir(mode=0o700)
                        paths.add(stage)
                        sync_directory(scratch)
                        _recover_directory(_target(root, segment.sequence), stage, contract_sha)
                        staged[segment.sequence] = (
                            stage,
                            pool.submit(
                                _prepare,
                                segment,
                                stage,
                                schema,
                                maximum,
                                record_bytes,
                                max_rows,
                                ledger_bytes,
                                contract_sha,
                            ),
                        )
                    for segment in window:
                        target = _target(root, segment.sequence)
                        if segment.sequence <= highest:
                            yield _reuse(
                                db, target, segment, contract_sha, maximum, 4 * ledger_bytes
                            )
                            continue
                        stage, future = staged[segment.sequence]
                        prepared = future.result()
                        _commit(db, target, stage, segment, prepared.receipt)
                        highest = segment.sequence
                        shutil.rmtree(stage)
                        paths.remove(stage)
                        del staged[segment.sequence]
                        yield JSONLSegmentResult(
                            segment.sequence,
                            segment.sha256,
                            hashlib.sha256(prepared.receipt).hexdigest(),
                            prepared.source_bytes,
                            prepared.rows,
                            target,
                            False,
                        )
                finally:
                    for _, future in staged.values():
                        future.cancel()
                    # Threads cannot write into a directory after its cleanup.
                    wait([future for _, future in staged.values()])
                    for stage in paths:
                        shutil.rmtree(stage)


def _reuse(
    db: sqlite3.Connection,
    target: Path,
    segment: SealedJSONL,
    contract_sha: str,
    maximum: int,
    file_limit: int,
) -> JSONLSegmentResult:
    saved = db.execute(
        "SELECT source_sha256,CASE WHEN typeof(receipt)='blob' AND length(receipt)<=? "
        "THEN receipt END FROM segments WHERE sequence=?",
        (_RECEIPT_BYTES, segment.sequence),
    ).fetchone()
    _require(
        saved is not None and saved[0] == segment.sha256 and isinstance(saved[1], bytes),
        "The segment number is already committed with a different identity",
    )
    assert saved is not None
    return _verify(target, saved[1], segment, contract_sha, maximum, file_limit)


def prepare_jsonl_segments(
    segments: Iterable[SealedJSONL],
    *,
    workspace: Path,
    schema: dict[str, Any] | None = None,
    workers: int = 1,
    max_segment_bytes: int = _MAX_BYTES,
    max_record_bytes: int = _MIB,
    max_segment_rows: int = 100_000,
) -> Generator[JSONLSegmentResult, None, None]:
    """Yield durable results in number order for a bounded window of sealed inputs.

    Supply a finite iterable of increasing numbered, complete UTF-8 JSONL
    files containing at least one record. Each part uses an independent
    ledger and retains local line proofs. Read only bundles returned by the
    API; staging directories and uncommitted bundles are not results.
    The workspace is private, with one writer. Call again with the next batch,
    or resubmit the same numbers and digests to verify and reuse committed work.
    A result refers to a committed bundle. If a later segment fails, the caller
    can retry from that number. Close the iterator if stopping early.
    """
    _require(_integer(workers) and 1 <= workers <= 4, "Use one to four segment workers")
    _require(
        _integer(max_segment_bytes)
        and 1 <= max_segment_bytes <= _MAX_BYTES
        and _integer(max_record_bytes)
        and 1 <= max_record_bytes <= _MIB
        and _integer(max_segment_rows)
        and 1 <= max_segment_rows <= 100_000,
        "Invalid sealed JSONL byte, record or row limit",
    )
    try:
        root = _workspace(workspace)
        plan = SchemaBuilder.normalize(schema if schema is not None else {})
        validate_stream_schema(plan)
        contract = _json(
            {
                "version": 1,
                "schema": plan,
                "max_segment_bytes": max_segment_bytes,
                "max_record_bytes": max_record_bytes,
                "max_segment_rows": max_segment_rows,
            }
        )
        _require(len(contract) <= 65_536, "The sealed JSONL contract exceeds its byte limit")
        yield from _prepare_segments(
            segments,
            root,
            plan,
            contract,
            workers,
            max_segment_bytes,
            max_record_bytes,
            max_segment_rows,
        )
    except (ExtractionError, OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        raise StreamError("Cannot prepare sealed JSONL segments: " + str(error)) from error
