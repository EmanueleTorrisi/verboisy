# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Ordinary research contracts, independent of execution and ledger orchestration.

Top-level id is generated output metadata. Source IDs require an explicit
projection to source_id; generic schema validation and streaming retain IDs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from verboisy.evidence.models import TaskSpec
from verboisy.extractor.schema_paths import SchemaPathIndex
from verboisy.utils.exceptions import VerboisyError


def validate_identity_fields(identity: Sequence[str], schema: dict[str, Any]) -> list[str]:
    """Validate 1..20 unique scalar RFC 6901 pointers, with no array identity."""
    if isinstance(identity, str | bytes) or not 1 <= len(identity) <= 20:
        raise VerboisyError("Identity requires 1 to 20 scalar JSON pointers")
    index = SchemaPathIndex.build(schema)
    result: list[str] = []
    for pointer in identity:
        if (
            not isinstance(pointer, str)
            or not pointer.startswith("/")
            or re.search(r"~(?![01])", pointer)
            or pointer not in index.fields
            or index.array_positions[pointer]
            or pointer in index.ambiguous
            or index.fields[pointer].get("type") in ("object", "array")
        ):
            raise VerboisyError("Identity must name unambiguous scalar RFC 6901 schema fields")
        if pointer in result:
            raise VerboisyError("Duplicate identity pointer")
        result.append(pointer)
    return result


def validate_research_contract(schema: dict[str, Any], task: TaskSpec) -> None:
    """Validate resolved task and explicit policies before creating saved state."""
    try:
        TaskSpec.model_validate(task.model_dump())
    except ValidationError:
        raise VerboisyError("Invalid resolved task specification") from None
    index = SchemaPathIndex.build(schema)
    if any(pointer not in index.fields for pointer in index.ambiguous):
        raise VerboisyError("Unresolved recursive explicit policy; use a finite declared shape")
    if "id" in index.properties:
        raise VerboisyError(
            "Top-level id is reserved output metadata; project source IDs to source_id"
        )
    if task.identity_fields:
        validate_identity_fields(task.identity_fields, schema)
    if (
        schema.get("type") == "array"
        and task.target_records is not None
        and not schema.get("minItems", 0) <= task.target_records <= schema.get("maxItems", 100000)
    ):
        raise VerboisyError("Target conflicts with schema collection limits")
    for pointer, field in index.fields.items():
        explicit = {k: v for k, v in field.items() if k.startswith("x-verboisy-")}
        if (explicit or "format" in field) and pointer in index.ambiguous:
            raise VerboisyError("Ambiguous explicit field policy; use a declared unambiguous shape")
        for key, value in explicit.items():
            if key not in {
                "x-verboisy-temporal-class",
                "x-verboisy-reference-period",
                "x-verboisy-definition-sensitive",
                "x-verboisy-unit-sensitive",
                "x-verboisy-methodology-sensitive",
                "x-verboisy-comparable-across-rows",
                "x-verboisy-dimension",
            }:
                raise VerboisyError("Unknown explicit field policy annotation")
            if key == "x-verboisy-temporal-class" and value not in (
                "static",
                "slow_changing",
                "mutable",
                "event",
                "time_series",
                "unknown",
            ):
                raise VerboisyError("Invalid explicit temporal field policy")
            if key == "x-verboisy-reference-period" and value not in (
                "none",
                "preferred",
                "required",
            ):
                raise VerboisyError("Invalid explicit reference-period policy")
            if key in (
                "x-verboisy-definition-sensitive",
                "x-verboisy-unit-sensitive",
                "x-verboisy-methodology-sensitive",
                "x-verboisy-comparable-across-rows",
            ) and not isinstance(value, bool):
                raise VerboisyError("Explicit field policy flags must be Boolean")
