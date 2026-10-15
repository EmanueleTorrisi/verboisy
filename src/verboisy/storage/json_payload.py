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
from typing import Any

from verboisy.utils.json_payload import decode_json


def decode_saved_json(payload: str | bytes | bytearray) -> Any:
    """Compatibility boundary retaining strict JSON and historical shape."""
    # Historical portable bundles accepted BOM/UTF-16/32 JSON bytes. Preserve
    # that reader contract; external configuration and model text remain UTF-8.
    if isinstance(payload, bytes | bytearray):
        payload = bytes(payload).decode(json.detect_encoding(payload))
    return decode_json(payload)


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
