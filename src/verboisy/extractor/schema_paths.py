# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded Draft 2020-12 introspection without weakening JSON Schema validation.

Only schema-declared array positions match indices. Object tokens, including
numeric names and literal stars, retain their RFC 6901 spelling. Resolution uses
public referencing resources with no remote retrieval.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import Any

from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from verboisy.utils.exceptions import ExtractionError


def matches(
    pattern: str, pointer: str, positions: tuple[int, ...], minimums: tuple[int, ...] = ()
) -> bool:
    expected, actual = pattern.split("/")[1:], pointer.split("/")[1:]
    floors = dict(zip(positions, minimums, strict=False))

    def array_token(token: str, minimum: int) -> bool:
        # String comparison avoids converting hostile, arbitrarily long indices.
        bound = str(minimum)
        return bool(re.fullmatch(r"0|[1-9][0-9]*", token)) and (
            len(token) > len(bound) or len(token) == len(bound) and token >= bound
        )

    return len(expected) == len(actual) and all(
        array_token(right, floors.get(index, 0)) if index in positions else left == right
        for index, (left, right) in enumerate(zip(expected, actual, strict=True))
    )


@dataclass(frozen=True)
class SchemaPathIndex:
    """Immutable path inventory, capped at 64 levels, 10,000 nodes and 1,000 leaves."""

    properties: tuple[str, ...]
    fields: Mapping[str, Mapping[str, Any]]
    array_positions: Mapping[str, tuple[int, ...]]
    unresolved: tuple[str, ...]
    ambiguous: tuple[str, ...]
    array_minimums: Mapping[str, tuple[int, ...]] = dataclass_field(default_factory=dict)

    def field(self, pointer: str) -> dict[str, Any] | None:
        if pointer in self.fields and not self.array_positions[pointer]:
            return dict(self.fields[pointer])
        candidates = [
            p
            for p in self.fields
            if matches(p, pointer, self.array_positions[p], self.array_minimums.get(p, ()))
        ]
        if not candidates:
            return None
        best = min(len(self.array_positions[p]) for p in candidates)
        candidates = [p for p in candidates if len(self.array_positions[p]) == best]
        if len(candidates) != 1:
            raise ExtractionError("Ambiguous schema field policy")
        return dict(self.fields[candidates[0]])

    @classmethod
    def build(cls, schema: dict[str, Any]) -> SchemaPathIndex:
        def sanitize(node: Any, depth: int = 0) -> Any:
            if depth > 64:
                raise ExtractionError("Schema introspection exceeds 64 levels")
            if not isinstance(node, dict):
                return node
            result = dict(node)
            for key in (
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
            ):
                if isinstance(node.get(key), dict):
                    result[key] = {
                        name: sanitize(child, depth + 1)
                        for name, child in node[key].items()
                        if isinstance(child, dict | bool)
                    }
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                if isinstance(node.get(key), list):
                    result[key] = [
                        sanitize(child, depth + 1)
                        for child in node[key]
                        if isinstance(child, dict | bool)
                    ]
            for key in ("items", "contains", "additionalProperties", "if", "then", "else", "not"):
                if isinstance(node.get(key), dict):
                    result[key] = sanitize(node[key], depth + 1)
            return result

        schema = sanitize(schema)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        base = schema.get("$id", "urn:verboisy:schema")
        registry: Registry[Any] = Registry().with_resource(base, resource).crawl()
        resolver = registry.resolver(base)
        fields: dict[str, dict[str, Any]] = {}
        arrays: dict[str, tuple[int, ...]] = {}
        minimums: dict[str, tuple[int, ...]] = {}
        array_floors: dict[str, int] = {}
        properties: list[str] = []
        unresolved: list[str] = []
        ambiguous: list[str] = []
        count = 0

        def add(pointer: str, node: dict[str, Any], positions: tuple[int, ...]) -> None:
            parts = pointer.split("/")
            bounds = tuple(
                array_floors.get("/".join(parts[: position + 2]), 0) for position in positions
            )
            previous = fields.get(pointer, {})
            conflicts = [
                k
                for k in previous.keys() & node.keys()
                if previous[k] != node[k] and (k == "format" or k.startswith("x-verboisy-"))
            ]
            if conflicts or (
                pointer in arrays and (arrays[pointer] != positions or minimums[pointer] != bounds)
            ):
                ambiguous.append(pointer)
            fields[pointer] = {**previous, **node}
            arrays[pointer] = positions
            minimums[pointer] = bounds
            if len(fields) > 1000:
                raise ExtractionError("Schema introspection exceeds 1,000 scalar paths")

        def walk(
            node: Any,
            pointer: str,
            positions: tuple[int, ...],
            scope: Any,
            stack: tuple[int, ...],
            depth: int,
            conditional: bool = False,
        ) -> None:
            nonlocal count
            count += 1
            if depth > 64 or count > 10_000:
                raise ExtractionError("Schema introspection exceeds 64 levels or 10,000 nodes")
            if isinstance(node, bool) or not isinstance(node, dict) or not node:
                return
            if id(node) in stack:
                unresolved.append(pointer or "/")
                if any(k.startswith("x-verboisy-") for k in node):
                    ambiguous.append(pointer or "/")
                return
            stack = (*stack, id(node))
            if "$id" in node and node is not schema:
                scope = scope.in_subresource(
                    Resource.from_contents(node, default_specification=DRAFT202012)
                )
            ref = node.get("$ref", node.get("$dynamicRef"))
            if ref is not None:
                try:
                    resolved = scope.lookup(ref)
                except (Unresolvable, ValueError) as error:
                    raise ExtractionError("Unresolved local schema reference") from error
                if id(resolved.contents) in stack and any(
                    k.startswith("x-verboisy-") or k == "format" for k in node
                ):
                    ambiguous.append(pointer or "/")
                walk(
                    resolved.contents,
                    pointer,
                    positions,
                    resolved.resolver,
                    stack,
                    depth + 1,
                    conditional,
                )
            for key in ("allOf", "anyOf", "oneOf"):
                for branch in node.get(key, []):
                    walk(
                        branch,
                        pointer,
                        positions,
                        scope,
                        stack,
                        depth + 1,
                        conditional or key != "allOf",
                    )
            for key in ("if", "then", "else", "dependentSchemas"):
                branch = node.get(key)
                if key == "dependentSchemas" and isinstance(branch, dict):
                    for child in branch.values():
                        walk(child, pointer, positions, scope, stack, depth + 1, True)
                elif branch is not None:
                    walk(branch, pointer, positions, scope, stack, depth + 1, True)
            if not pointer and "id" in node.get("required", []) and "id" not in properties:
                properties.append("id")
            props = node.get("properties")
            if isinstance(props, dict):
                for name, child in props.items():
                    if not pointer and name not in properties:
                        properties.append(name)
                    token = name.replace("~", "~0").replace("/", "~1")
                    walk(
                        child,
                        pointer + "/" + token,
                        positions,
                        scope,
                        stack,
                        depth + 1,
                        conditional,
                    )
            elif node.get("type") == "array" or "items" in node or "prefixItems" in node:
                for index, child in enumerate(node.get("prefixItems", [])):
                    walk(
                        child,
                        pointer + f"/{index}",
                        positions,
                        scope,
                        stack,
                        depth + 1,
                        conditional,
                    )
                if isinstance(node.get("items"), dict):
                    array_floors[pointer + "/*"] = len(node.get("prefixItems", []))
                    index = len(pointer.split("/")) - 1
                    walk(
                        node["items"],
                        pointer + "/*",
                        (*positions, index),
                        scope,
                        stack,
                        depth + 1,
                        conditional,
                    )
            elif (
                pointer
                and "$ref" not in node
                and "$dynamicRef" not in node
                and node.get("type") not in ("object", "array")
            ):
                add(pointer, node, positions)
                if conditional:
                    ambiguous.append(pointer)
            # Sibling annotations of a reference/applicator apply to its resolved leaf.
            if pointer in fields:
                annotations = {
                    k: v
                    for k, v in node.items()
                    if k.startswith("x-") or k in ("format", "description", "title")
                }
                if annotations:
                    add(pointer, annotations, positions)

        if schema.get("type") == "array":
            walk(schema.get("items"), "", (), resolver, (), 0)
        else:
            walk(schema, "", (), resolver, (), 0)
        return cls(
            tuple(properties),
            MappingProxyType({pointer: MappingProxyType(node) for pointer, node in fields.items()}),
            MappingProxyType(arrays),
            tuple(dict.fromkeys(unresolved)),
            tuple(dict.fromkeys(ambiguous)),
            MappingProxyType(minimums),
        )
