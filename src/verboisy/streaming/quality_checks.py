# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Evaluate row counts, field population and typed uniqueness in bounded space."""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from verboisy.streaming.contract import StreamError
from verboisy.streaming.quality_contract import _Contract, _FieldRule, _UniqueRule
from verboisy.streaming.record_keys import MISSING, RecordKeyError, field_value, record_key

_SAMPLE_LIMIT = 3
_COMMIT_ROWS = 4096


@dataclass(frozen=True)
class _Row:
    ordinal: int
    first_line: int | None
    last_line: int | None
    value: dict[str, Any]


@dataclass(frozen=True)
class QualityFinding:
    reason: str
    ordinal: int
    first_line: int | None
    last_line: int | None
    first_ordinal: int | None = None


@dataclass(frozen=True)
class RowCountCheck:
    min_rows: int
    max_rows: int | None
    passed: bool


@dataclass(frozen=True)
class CompletenessCheck:
    field: str
    min_present_percent: int
    present: int
    missing: int
    null: int
    blank: int
    passed: bool
    examples: tuple[QualityFinding, ...]


@dataclass(frozen=True)
class UniquenessCheck:
    fields: tuple[str, ...]
    invalid: int
    duplicates: int
    passed: bool
    examples: tuple[QualityFinding, ...]


@dataclass(frozen=True)
class _Assessment:
    passed: bool
    rows: int
    row_count: RowCountCheck
    completeness: tuple[CompletenessCheck, ...]
    uniqueness: tuple[UniquenessCheck, ...]


class _Tally:
    def __init__(self, *reasons: str) -> None:
        self.counts = dict.fromkeys(reasons, 0)
        self.examples: list[QualityFinding] = []

    def add(self, reason: str, row: _Row, first: int | None = None) -> None:
        self.counts[reason] += 1
        if len(self.examples) < _SAMPLE_LIMIT:
            self.examples.append(
                QualityFinding(reason, row.ordinal, row.first_line, row.last_line, first)
            )


@contextmanager
def _index(folder: Path, max_bytes: int) -> Iterator[sqlite3.Connection]:
    try:
        with (
            TemporaryDirectory(
                prefix=".verboisy-quality-", dir=folder, ignore_cleanup_errors=True
            ) as scratch,
            closing(sqlite3.connect(Path(scratch) / "keys.db")) as db,
        ):
            db.execute("PRAGMA page_size=4096")
            db.execute(f"PRAGMA max_page_count={max_bytes // 4096}")
            db.execute("PRAGMA cache_size=-4096")
            # A private, disposable index never serves as a published report.
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute(
                "CREATE TABLE seen(rule INTEGER NOT NULL,key BLOB NOT NULL,"
                "ordinal INTEGER NOT NULL,"
                "PRIMARY KEY(rule,key)) WITHOUT ROWID"
            )
            yield db
    except (OSError, sqlite3.Error) as error:
        raise StreamError("Cannot complete the quality index within its storage limit") from error


def _check_field(row: _Row, rule: _FieldRule, tally: _Tally) -> None:
    value = field_value(row.value, rule.path)
    if value is MISSING:
        tally.add("missing", row)
    elif value is None:
        tally.add("null", row)
    elif isinstance(value, str) and not value.strip():
        tally.add("blank", row)


def _check_key(
    db: sqlite3.Connection, number: int, row: _Row, rule: _UniqueRule, tally: _Tally
) -> None:
    try:
        key = record_key(row.value, rule.paths, row.ordinal)
    except RecordKeyError:
        tally.add("invalid", row)
        return
    inserted = db.execute(
        "INSERT INTO seen VALUES(?,?,?) ON CONFLICT(rule,key) DO NOTHING",
        (number, key, row.ordinal),
    )
    if inserted.rowcount == 0:
        first = None
        if len(tally.examples) < _SAMPLE_LIMIT:
            first = db.execute(
                "SELECT ordinal FROM seen WHERE rule=? AND key=?", (number, key)
            ).fetchone()[0]
        tally.add("duplicate", row, first)


def _field_result(rule: _FieldRule, tally: _Tally, count: int) -> CompletenessCheck:
    present = count - sum(tally.counts.values())
    return CompletenessCheck(
        rule.field,
        rule.min_present_percent,
        present,
        tally.counts["missing"],
        tally.counts["null"],
        tally.counts["blank"],
        present * 100 >= rule.min_present_percent * count,
        tuple(tally.examples),
    )


def _unique_result(rule: _UniqueRule, tally: _Tally) -> UniquenessCheck:
    return UniquenessCheck(
        rule.fields,
        tally.counts["invalid"],
        tally.counts["duplicate"],
        not any(tally.counts.values()),
        tuple(tally.examples),
    )


def assess(
    rows: Iterable[_Row],
    contract: _Contract,
    *,
    expected_rows: int,
    folder: Path,
    max_index_bytes: int,
) -> _Assessment:
    fields = [_Tally("missing", "null", "blank") for _ in contract.completeness]
    keys = [_Tally("invalid", "duplicate") for _ in contract.unique]
    count = 0
    with _index(folder, max_index_bytes) if keys else nullcontext() as db:
        for count, row in enumerate(rows, 1):
            for field, field_tally in zip(contract.completeness, fields, strict=True):
                _check_field(row, field, field_tally)
            if db is not None:
                for number, (rule, key_tally) in enumerate(zip(contract.unique, keys, strict=True)):
                    _check_key(db, number, row, rule, key_tally)
                if count % _COMMIT_ROWS == 0:
                    db.commit()
        if db is not None:
            db.commit()
    if count != expected_rows:
        raise StreamError("Quality replay did not reach its declared row count")
    row_count = RowCountCheck(
        contract.min_rows,
        contract.max_rows,
        count >= contract.min_rows and (contract.max_rows is None or count <= contract.max_rows),
    )
    completeness = tuple(
        _field_result(field, tally, count)
        for field, tally in zip(contract.completeness, fields, strict=True)
    )
    uniqueness = tuple(
        _unique_result(rule, tally) for rule, tally in zip(contract.unique, keys, strict=True)
    )
    passed = (
        row_count.passed
        and all(rule.passed for rule in completeness)
        and all(rule.passed for rule in uniqueness)
    )
    return _Assessment(passed, count, row_count, completeness, uniqueness)
