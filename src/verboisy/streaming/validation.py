# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compile a conservative structural schema subset; retain authoritative fallback.

Only type, properties, required, boolean additionalProperties and homogeneous
items are accelerated. Unknown keywords fall back for the entire row schema.
The reference type checker is reused; no values are converted or discarded.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from verboisy.extractor.schema_builder import SchemaBuilder

Check = Callable[[Any], bool]
_ANNOTATIONS = frozenset(
    {
        "title",
        "description",
        "default",
        "examples",
        "readOnly",
        "writeOnly",
        "deprecated",
        "$comment",
    }
)
_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})


@dataclass(frozen=True)
class RowValidator:
    reference: Draft202012Validator
    compiled: Check | None

    def is_valid(self, value: Any) -> bool:
        if self.compiled is None:
            return bool(self.reference.is_valid(value))
        return self.compiled(value)


def row_validator(schema: dict[str, Any]) -> RowValidator:
    """Validate and freeze the schema once, keeping root reference resolution."""
    root = SchemaBuilder.validator(schema)
    reference = root.evolve(schema=root.schema["items"]) if root.schema["type"] == "array" else root
    return RowValidator(reference, _compile(reference.schema, reference, [512], 0))


def _compile(
    schema: dict[str, Any] | bool,
    reference: Draft202012Validator,
    remaining: list[int],
    depth: int,
) -> Check | None:
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 32:
        return None
    if isinstance(schema, bool):
        return lambda _value: schema
    keys = set(schema) - _ANNOTATIONS
    if not keys:
        return lambda _value: True
    kind = schema.get("type")
    checker = reference.TYPE_CHECKER
    if isinstance(kind, list):
        if keys != {"type"} or not kind or any(item not in _TYPES for item in kind):
            return None
        types = tuple(kind)
        return lambda value: any(checker.is_type(value, item) for item in types)
    if not isinstance(kind, str) or kind not in _TYPES:
        return None
    if kind == "object":
        if keys - {"type", "properties", "required", "additionalProperties"}:
            return None
        extra = schema.get("additionalProperties", True)
        if not isinstance(extra, bool):
            return None
        fields: list[tuple[str, Check]] = []
        for name, definition in schema.get("properties", {}).items():
            child = _compile(definition, reference, remaining, depth + 1)
            if child is None:
                return None
            fields.append((name, child))
        required = frozenset(schema.get("required", []))
        allowed = frozenset(schema.get("properties", {}))

        def object_check(value: Any) -> bool:
            if not checker.is_type(value, "object") or not required <= value.keys():
                return False
            if not extra and not value.keys() <= allowed:
                return False
            return all(check(value[name]) for name, check in fields if name in value)

        return object_check
    if kind == "array":
        if keys - {"type", "items"}:
            return None
        item_check = _compile(schema.get("items", True), reference, remaining, depth + 1)
        if item_check is None:
            return None
        return lambda value: checker.is_type(value, "array") and all(item_check(v) for v in value)
    if keys != {"type"}:
        return None
    return lambda value: bool(checker.is_type(value, kind))
