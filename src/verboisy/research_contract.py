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
    if task.html_metadata is not None:
        _validate_html_metadata(schema, task)
    if task.html_table is not None:
        _validate_html_table(schema, task)
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


def _validate_html_table(schema: dict[str, Any], task: TaskSpec) -> None:
    from verboisy.evidence.snapshot import canonical_url

    plan = task.html_table
    assert plan is not None
    seeds = task.seed_urls
    if (
        len(seeds) != 1
        or canonical_url(seeds[0]) != seeds[0]
        or task.target_records != len(plan.keys)
        or task.identity_fields != ["/" + plan.key_field]
    ):
        raise VerboisyError(
            "HTML table bindings require one canonical seed, the declared key as identity, "
            "and one target record per key"
        )
    record = _closed_literal_record(schema, set(plan.fields), "HTML table")
    for name, binding in plan.fields.items():
        field = record["properties"][name]
        expected_type = "string" if binding.value_type == "text" else "integer"
        if (
            not isinstance(field, dict)
            or field.get("type") != expected_type
            or _nonliteral_field(field)
        ):
            raise VerboisyError(
                "HTML table bindings require explicit matching string or integer fields"
            )


def _nonliteral_field(field: dict[str, Any]) -> bool:
    return any(
        key.startswith("x-verboisy-")
        or key in {"$ref", "allOf", "anyOf", "oneOf", "if", "then", "else"}
        for key in field
    )


def _closed_literal_record(schema: dict[str, Any], fields: set[str], mode: str) -> dict[str, Any]:
    record = schema.get("items") if schema.get("type") == "array" else schema
    if (
        not isinstance(record, dict)
        or record.get("type") != "object"
        or record.get("additionalProperties") is not False
        or not isinstance(record.get("properties"), dict)
        or not isinstance(record.get("required"), list)
        or any(not isinstance(name, str) for name in record["required"])
        or record["properties"].keys() != fields
        or set(record["required"]) != fields
    ):
        raise VerboisyError(mode + " bindings must exactly match a closed flat record schema")
    return record


def _validate_html_metadata(schema: dict[str, Any], task: TaskSpec) -> None:
    from verboisy.evidence.snapshot import canonical_url

    plan = task.html_metadata
    assert plan is not None
    seeds = task.seed_urls
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(canonical_url(url) != url for url in seeds)
        or task.target_records != len(seeds)
        or task.max_pages < len(seeds)
    ):
        raise VerboisyError(
            "HTML metadata requires distinct canonical seeds and one target record per seed"
        )
    record = _closed_literal_record(schema, set(plan.fields), "HTML metadata")
    required = {
        "/" + name for name, binding in plan.fields.items() if binding.on_missing == "error"
    }
    if not task.identity_fields or not set(task.identity_fields) <= required:
        raise VerboisyError(
            "HTML metadata requires an explicit identity made of nonmissing bindings"
        )
    for name, binding in plan.fields.items():
        field = record["properties"][name]
        kind = field.get("type") if isinstance(field, dict) else None
        nullable = kind in (["string", "null"], ["null", "string"])
        if (
            not isinstance(field, dict)
            or (kind != "string" and not nullable)
            or _nonliteral_field(field)
        ):
            raise VerboisyError("HTML metadata accepts only explicit literal string fields")
        if binding.on_missing == "null" and (not task.allow_nulls or not nullable):
            raise VerboisyError(
                "A missing HTML field may be null only when the task and schema allow it"
            )
