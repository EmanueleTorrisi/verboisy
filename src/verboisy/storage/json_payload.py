# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Decode unambiguous, finite saved JSON without changing its historical shape.

Callers own model validation and their public error messages. This boundary
rejects repeated object keys at every depth, including escaped equivalents, and
numbers which overflow Python's finite float representation. It does not infer
replacement values or rewrite saved evidence.
"""

from __future__ import annotations

import json
import math
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate saved JSON object key")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Non-finite saved JSON number")
    return value


def _reject_constant(_text: str) -> Any:
    raise ValueError("Non-finite saved JSON constant")


def decode_saved_json(payload: str | bytes | bytearray) -> Any:
    """Retain JSON values and object order; reject ambiguity before model coercion."""
    return json.loads(
        payload,
        object_pairs_hook=_unique_object,
        parse_float=_finite_float,
        parse_constant=_reject_constant,
    )


def copy_saved_json(value: Any) -> Any:
    """Clone containers in decoded JSON while retaining its immutable scalar values.

    Use only for JSON already decoded and validated by the caller. Unlike generic
    deep copying, this boundary need not inspect arbitrary Python object state.
    Dictionary order, optional-field omissions and nested container isolation stay
    intact without a second parse or validation of the same saved payload.
    """
    if isinstance(value, dict):
        return {key: copy_saved_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copy_saved_json(item) for item in value]
    return value
