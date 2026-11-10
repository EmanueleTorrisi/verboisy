# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit physical types and resource limits for analytical export bundles."""

import json
from dataclasses import dataclass
from typing import Any

from verboisy.streaming.contract import StreamError

MAX_SCHEMA_BYTES = 65_536
MAX_COLUMNS = 128
MAX_SHARDS = 10_000
SHARD_PAYLOAD_BYTES = 128 * 1024**2
GROUP_BYTES = 16 * 1024**2
GROUP_ROWS = 8_192
DEFAULT_SHARD_ROWS = 250_000
DEFAULT_OUTPUT_BYTES = 32 * 1024**3
TYPES = frozenset({"bool", "int64", "float64", "string", "json"})


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    nullable: bool


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def columns_for(output_format: str, schema: dict[str, Any] | None) -> tuple[Column, ...]:
    if output_format == "jsonl":
        if schema is not None:
            raise StreamError("The column contract is only used for Parquet")
        return ()
    if output_format != "parquet":
        raise StreamError("Analytical export format must be jsonl or parquet")
    if (
        not isinstance(schema, dict)
        or schema.keys() != {"version", "columns"}
        or schema["version"] != "1"
        or not isinstance(schema["columns"], list)
        or not 1 <= len(schema["columns"]) <= MAX_COLUMNS
    ):
        raise StreamError("Parquet requires a version '1' column contract with 1 to 128 columns")
    columns: list[Column] = []
    seen: set[str] = set()
    for entry in schema["columns"]:
        if not isinstance(entry, dict) or entry.keys() != {"name", "type", "nullable"}:
            raise StreamError("Each Parquet column requires name, type and nullable")
        name, kind, nullable = entry["name"], entry["type"], entry["nullable"]
        if (
            not isinstance(name, str)
            or not name.isprintable()
            or not 1 <= len(name.encode("utf-8")) <= 128
            or name in seen
        ):
            raise StreamError(
                "Parquet column names must be unique printable UTF-8 (1 to 128 bytes)"
            )
        if not isinstance(kind, str) or kind not in TYPES or not isinstance(nullable, bool):
            raise StreamError(
                "Column type must be bool, int64, float64, string or json; nullable is boolean"
            )
        seen.add(name)
        columns.append(Column(name, kind, nullable))
    return tuple(columns)


def validate_limits(shard_rows: int, max_output_bytes: int) -> None:
    if (
        isinstance(shard_rows, bool)
        or not isinstance(shard_rows, int)
        or not 1 <= shard_rows <= 1_000_000
    ):
        raise StreamError("Rows per analytical shard must be an integer from 1 to 1,000,000")
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes < 1
    ):
        raise StreamError("The analytical output limit must be a positive byte count")


def typed_cell(column: Column, value: Any) -> Any:
    """The input comes from the strict replay decoder; never coerce scalar types."""
    kind = column.kind
    if value is None:
        if column.nullable:
            return None
    elif kind == "json":
        return json_bytes(value).decode("utf-8")
    elif (
        (kind == "string" and isinstance(value, str))
        or (kind == "bool" and isinstance(value, bool))
        or (
            kind == "int64"
            and isinstance(value, int)
            and not isinstance(value, bool)
            and -(2**63) <= value < 2**63
        )
        or (kind == "float64" and isinstance(value, float))
    ):
        return value
    raise StreamError(f"Verified value does not match Parquet column {column.name!r} ({kind})")
