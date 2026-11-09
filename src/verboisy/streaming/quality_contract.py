# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Strict, versioned dataset quality rules compiled once per evaluation."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from verboisy.streaming.contract import StreamError
from verboisy.streaming.record_keys import field_path, key_paths

MAX_CONTRACT_BYTES = 65_536
DEFAULT_INDEX_BYTES = 4 * 1024**3
_MAX_ROWS = 2**63 - 1


@dataclass(frozen=True)
class _FieldRule:
    field: str
    path: tuple[str, ...]
    min_present_percent: int


@dataclass(frozen=True)
class _UniqueRule:
    fields: tuple[str, ...]
    paths: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class _Contract:
    min_rows: int
    max_rows: int | None
    completeness: tuple[_FieldRule, ...]
    unique: tuple[_UniqueRule, ...]
    sha256: str


def _integer(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise StreamError(f"{name} must be an integer between {low} and {high}")
    return value


def validate_index_limit(value: int) -> int:
    return _integer(value, "max_index_bytes", 65536, 16 * 1024**4)


def _list(value: object, name: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise StreamError(f"{name} must be an array of at most {maximum} rules")
    return value


def _fields(entries: list[Any]) -> tuple[_FieldRule, ...]:
    rules = []
    seen = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or "field" not in entry
            or set(entry) - {"field", "min_present_percent"}
        ):
            raise StreamError("Completeness rules require field and optional min_present_percent")
        field = entry["field"]
        path = field_path(field)
        if path in seen:
            raise StreamError("Completeness fields must be distinct")
        seen.add(path)
        percent = _integer(entry.get("min_present_percent", 100), "min_present_percent", 1, 100)
        rules.append(_FieldRule(field, path, percent))
    return tuple(rules)


def _groups(entries: list[Any]) -> tuple[_UniqueRule, ...]:
    rules = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, list):
            raise StreamError("Each unique rule must be an array of key pointers")
        fields = tuple(entry)
        paths = key_paths(fields)
        group = frozenset(paths)
        if group in seen:
            raise StreamError("Unique rules must use distinct field groups")
        seen.add(group)
        rules.append(_UniqueRule(fields, paths))
    return tuple(rules)


def compile_contract(value: dict[str, Any]) -> _Contract:
    if (
        not isinstance(value, dict)
        or value.get("version") != "1"
        or set(value) - {"version", "min_rows", "max_rows", "completeness", "unique"}
    ):
        raise StreamError("Choose a version 1 quality contract with supported fields")
    minimum = _integer(value.get("min_rows", 1), "min_rows", 0, _MAX_ROWS)
    upper = value.get("max_rows")
    maximum = None if upper is None else _integer(upper, "max_rows", minimum, _MAX_ROWS)
    completeness = _fields(_list(value.get("completeness", []), "completeness", 64))
    unique = _groups(_list(value.get("unique", []), "unique", 8))
    if minimum == 0 and maximum is None and not (completeness or unique):
        raise StreamError("Quality contract must contain at least one effective check")
    normalized = {
        "version": "1",
        "min_rows": minimum,
        "max_rows": maximum,
        "completeness": [
            {"field": rule.field, "min_present_percent": rule.min_present_percent}
            for rule in completeness
        ],
        "unique": [rule.fields for rule in unique],
    }
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return _Contract(minimum, maximum, completeness, unique, hashlib.sha256(payload).hexdigest())
