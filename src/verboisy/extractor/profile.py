# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded deterministic source profiles, never global uniqueness or identity claims."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from verboisy.extractor.dataset import ParsedDataset
from verboisy.utils.exceptions import VerboisyError


class DatasetProfileError(VerboisyError):
    """Invalid profiling limits or malformed captured values."""


@dataclass(frozen=True)
class ValuePreview:
    row_index: int
    json_preview: str
    truncated: bool


@dataclass(frozen=True)
class FieldProfile:
    pointer: str
    present_rows: int
    missing_rows: int
    null_rows: int
    observed_types: tuple[str, ...]
    distinct_values_sampled: int
    examples: tuple[ValuePreview, ...]


@dataclass(frozen=True)
class DatasetProfile:
    asset_sha256: str
    parser_version: str
    dataset_format: str
    total_rows: int
    sampled_rows: int
    sample_policy: str
    rows_truncated: bool
    fields_truncated: bool
    oversized_pointers_skipped: bool
    fields: tuple[FieldProfile, ...]
    profile_version: str = "1"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _observations(value: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    if pointer:
        yield pointer, value
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _observations(child, pointer + "/" + escaped)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _observations(child, pointer + f"/{index}")


def profile_dataset(
    dataset: ParsedDataset,
    *,
    sample_rows: int = 1000,
    max_fields: int = 100,
    max_examples: int = 3,
    preview_bytes: int = 128,
) -> DatasetProfile:
    """Profile a parsed capture using its first rows and first encountered paths.

    Hard caps bound rows (1000), fields (100), examples (5) and preview bytes (1024).
    Pointers over 512 UTF-8 bytes are omitted explicitly. Distinct counts describe
    only this sample, using SHA-256 of exact canonical JSON values. No conversion,
    alias inference, formula evaluation, network access or model call takes place.
    """
    for value, minimum, maximum in (
        (sample_rows, 1, 1000),
        (max_fields, 1, 100),
        (max_examples, 0, 5),
        (preview_bytes, 1, 1024),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise DatasetProfileError("Invalid dataset profiling limits")
    fields: dict[str, dict[str, Any]] = {}
    truncated, oversized = False, False
    sampled = dataset.rows[:sample_rows]
    try:
        for row in sampled:
            for pointer, value in _observations(row.values):
                if len(pointer.encode("utf-8")) > 512:
                    oversized = True
                    continue
                if pointer not in fields:
                    if len(fields) >= max_fields:
                        truncated = True
                        continue
                    fields[pointer] = {
                        "present": 0,
                        "nulls": 0,
                        "types": set(),
                        "digests": set(),
                        "examples": [],
                    }
                stats = fields[pointer]
                stats["present"] += 1
                stats["nulls"] += value is None
                stats["types"].add(_kind(value))
                encoded = json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                if digest not in stats["digests"]:
                    stats["digests"].add(digest)
                    if len(stats["examples"]) < max_examples:
                        preview = encoded[:preview_bytes].decode("utf-8", errors="ignore")
                        stats["examples"].append(
                            ValuePreview(row.row_index, preview, len(encoded) > preview_bytes)
                        )
    except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
        raise DatasetProfileError("Malformed values in parsed dataset") from None
    return DatasetProfile(
        dataset.sha256,
        dataset.parser_version,
        dataset.format,
        len(dataset.rows),
        len(sampled),
        "first_rows_first_paths",
        len(dataset.rows) > len(sampled),
        truncated,
        oversized,
        tuple(
            FieldProfile(
                pointer,
                stats["present"],
                len(sampled) - stats["present"],
                stats["nulls"],
                tuple(sorted(stats["types"])),
                len(stats["digests"]),
                tuple(stats["examples"]),
            )
            for pointer, stats in fields.items()
        ),
    )
