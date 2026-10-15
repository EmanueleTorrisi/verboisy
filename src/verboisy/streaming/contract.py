# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit resource ceilings and count-based results for disk-backed preparation."""

from dataclasses import dataclass
from typing import Any

from verboisy.utils.exceptions import VerboisyError

FORMATS = frozenset({"csv", "tsv", "jsonl", "text", "asset"})
CHUNK_BYTES = 1_048_576
BATCH_ROWS = 512


class StreamError(VerboisyError):
    """A streaming contract, capture or checkpoint cannot be verified."""


@dataclass(frozen=True)
class StreamLimits:
    max_input_bytes: int = 8_589_934_592
    max_rows: int = 10_000_000
    max_record_bytes: int = 1_048_576
    max_storage_bytes: int = 17_179_869_184

    def __post_init__(self) -> None:
        for value in (
            self.max_input_bytes,
            self.max_rows,
            self.max_record_bytes,
            self.max_storage_bytes,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise StreamError("Streaming limits must be positive integers")
        if self.max_storage_bytes < 65_536 or self.max_record_bytes > 16_777_216:
            raise StreamError("Storage must allow 64 KiB; records may not exceed 16 MiB")


@dataclass(frozen=True)
class StreamResult:
    job_id: str
    status: str
    processed_rows: int
    input_bytes: int
    source_sha256: str | None
    reason: str | None


def validate_stream_schema(schema: dict[str, Any]) -> None:
    """Array roots support only item validation and reference/descriptive context."""
    if schema.get("type") != "array":
        return
    allowed = {
        "type",
        "items",
        "$schema",
        "$defs",
        "definitions",
        "$id",
        "$anchor",
        "$dynamicAnchor",
        "title",
        "description",
        "$comment",
        "default",
        "examples",
        "readOnly",
        "writeOnly",
        "deprecated",
    }
    unsupported = sorted(key for key in schema if key not in allowed and not key.startswith("x-"))
    if unsupported or not isinstance(schema.get("items"), dict):
        raise StreamError(
            "Streaming validates individual rows; unsupported array keywords: "
            + ", ".join(unsupported or ["items"])
        )
