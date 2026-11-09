# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Typed record identity shared by quality contracts and dataset updates."""

import json
import re
from typing import Any

from verboisy.streaming.contract import StreamError

MISSING = object()
_MAX_KEY_BYTES = 4096


class RecordKeyError(StreamError):
    """A record cannot supply a valid typed key."""


def field_path(pointer: str) -> tuple[str, ...]:
    if (
        not isinstance(pointer, str)
        or not pointer.startswith("/")
        or len(pointer) > 1024
        or re.search(r"~(?![01])", pointer)
    ):
        raise StreamError("Record key or field must be a non-root JSON pointer to object fields")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def field_value(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def key_paths(pointers: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if not isinstance(pointers, tuple) or not 1 <= len(pointers) <= 8:
        raise StreamError("Choose one to eight record key pointers")
    paths = tuple(field_path(pointer) for pointer in pointers)
    if len(set(paths)) != len(paths):
        raise StreamError("Record key pointers must be distinct")
    return paths


def record_key(record: dict[str, Any], paths: tuple[tuple[str, ...], ...], ordinal: int) -> bytes:
    values: list[str | int] = []
    for path in paths:
        value = field_value(record, path)
        if value is MISSING:
            raise RecordKeyError(f"Missing record key at row {ordinal}")
        if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
            raise RecordKeyError(
                f"Record key at row {ordinal} must be a nonempty string or integer"
            )
        if isinstance(value, str) and len(value) > _MAX_KEY_BYTES:
            raise RecordKeyError(f"Record key at row {ordinal} exceeds 4096 encoded bytes")
        values.append(value)
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _MAX_KEY_BYTES:
        raise RecordKeyError(f"Record key at row {ordinal} exceeds 4096 encoded bytes")
    return encoded
