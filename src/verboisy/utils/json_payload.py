# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Strict finite UTF-8 JSON and bounded, stable regular-file configuration reads.

Parsing rejects ambiguity without coercion. It is not a CPU sandbox for complex
trusted schemas. Callers translate payload-free errors at their public boundary.
"""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    return value


def _reject_constant(_text: str) -> Any:
    raise ValueError("Non-finite JSON constant")


def decode_json(payload: str | bytes | bytearray) -> Any:
    """Decode unique finite JSON; reject unsafe Unicode and excessive nesting."""
    if not isinstance(payload, str | bytes | bytearray):
        raise ValueError("JSON input must be text or bytes")
    try:
        text = bytes(payload).decode("utf-8") if isinstance(payload, bytes | bytearray) else payload
        text.encode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_finite_float,
            parse_constant=_reject_constant,
        )
        pending = [value]
        while pending:
            node = pending.pop()
            if isinstance(node, str):
                node.encode("utf-8")
            elif isinstance(node, dict):
                pending.extend(node.keys())
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("Invalid finite unique UTF-8 JSON") from error


def read_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read at most a positive byte ceiling from an unchanged regular file.

    Nonblocking open prevents FIFO reads from hanging before the type check.
    Opened-object metadata binds the read, rather than a preceding path stat.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("Byte limit must be a positive integer")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Input must be a regular file")
        data = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
        if len(data) > max_bytes:
            raise ValueError("Input exceeds byte limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(data) != after.st_size:
            raise ValueError("Input changed while reading")
    return data


def read_json_object(path: Path, *, max_bytes: int = 1_048_576) -> dict[str, Any]:
    """Read bounded JSON configuration; raise ValueError for an invalid object."""
    value = decode_json(read_bytes(path, max_bytes=max_bytes))
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a JSON object")
    return value
