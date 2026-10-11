# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reuse private record validators without sharing mutable caller schemas."""

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from verboisy.extractor.schema_builder import SchemaBuilder

MAX_CACHED_SCHEMAS = 64
MAX_SCHEMA_BYTES = 65_536


def _json_value(value: Any) -> bool:
    # JSON round trips must preserve types. Non-JSON Python inputs still follow
    # the original builder path, including its original errors and semantics.
    if type(value) is dict:  # noqa: E721 - subclasses may change serialization behavior.
        return all(
            type(key) is str and _json_value(item)  # noqa: E721 - reject key coercion.
            for key, item in value.items()
        )
    if type(value) is list:  # noqa: E721 - subclasses retain the original path.
        return all(_json_value(item) for item in value)
    return type(value) in (str, int, float, bool, type(None))


@lru_cache(maxsize=MAX_CACHED_SCHEMAS)
def _compile(serialized: str) -> type[BaseModel]:
    # Only successful compilation is retained. The decoded schema belongs to
    # this model; mutating a caller's dictionary cannot change a cached contract.
    return SchemaBuilder.build_model("Record", json.loads(serialized))


def validate_record(record: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate every record; cache compilation only, never records or outcomes.

    The cache is process-local and bounded by entry count and serialized schema
    size. Oversized or non-JSON Python schemas retain the uncached builder path.
    Field order is preserved in the key rather than canonicalized away.
    """
    if not _json_value(schema):
        model = SchemaBuilder.build_model("Record", schema)
    else:
        try:
            serialized = json.dumps(
                schema, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            )
        except (TypeError, ValueError):
            model = SchemaBuilder.build_model("Record", schema)
        else:
            model = (
                _compile(serialized)
                if len(serialized.encode("utf-8")) <= MAX_SCHEMA_BYTES
                else SchemaBuilder.build_model("Record", schema)
            )
    model.model_validate(record)
