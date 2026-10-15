# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Schema-derived paths preserve literal tokens, local resources and bounded work."""

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.schema_paths import SchemaPathIndex
from verboisy.research_contract import validate_identity_fields, validate_research_contract
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize("items", [None, True, False, {}])
def test_generic_arrays_are_opaque(items):
    child = {"type": "array"}
    if items is not None:
        child["items"] = items
    index = SchemaPathIndex.build({"type": "object", "properties": {"rows": child}})
    assert not index.fields


@pytest.mark.parametrize("ref", ["#/$defs/day", "#day"])
def test_references_and_anchors(ref):
    schema = {
        "type": "object",
        "$defs": {"day": {"$anchor": "day", "type": "string", "format": "date"}},
        "properties": {"day": {"$ref": ref}},
    }
    assert SchemaPathIndex.build(schema).field("/day")["format"] == "date"


def test_array_positions_tuple_and_literal_tokens():
    schema = {
        "type": "object",
        "properties": {
            "2024": {"type": "number"},
            "*": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"2024": {"type": "number"}, "a/b~c": {"type": "string"}},
                },
            },
            "tuple": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
        },
    }
    index = SchemaPathIndex.build(schema)
    assert index.array_positions["/rows/*/2024"] == (1,)
    assert index.field("/rows/12/2024")["type"] == "number"
    assert index.field("/rows/012/2024") is None
    assert index.field("/rows/3/a~1b~0c")["type"] == "string"
    assert index.field("/2024")["type"] == "number"
    assert index.field("/*")["type"] == "string"
    assert index.field("/tuple/0")["type"] == "string"
    assert index.field("/tuple/1") is None


def test_cycle_outcome_and_unresolved_reference():
    schema = {"type": "object", "properties": {"node": {"$ref": "#"}}}
    assert SchemaPathIndex.build(schema).unresolved
    with pytest.raises(VerboisyError, match="reference"):
        SchemaPathIndex.build({"type": "object", "properties": {"x": {"$ref": "#missing"}}})


def test_policy_ambiguity_and_allof():
    schema = {
        "type": "object",
        "allOf": [
            {"properties": {"n": {"type": "integer"}}},
            {"properties": {"n": {"x-verboisy-reference-period": "required"}}},
        ],
    }
    assert SchemaPathIndex.build(schema).fields["/n"]["type"] == "integer"
    validate_research_contract(schema, TaskSpec())
    schema = {
        "type": "object",
        "oneOf": [
            {"properties": {"n": {"type": "integer", "x-verboisy-reference-period": "required"}}},
            {"properties": {"n": {"type": "integer"}}},
        ],
    }
    with pytest.raises(VerboisyError, match="Ambiguous"):
        validate_research_contract(schema, TaskSpec())
    with pytest.raises(VerboisyError):
        validate_identity_fields(["/n"], schema)


@pytest.mark.parametrize("case", ["depth", "paths", "nodes"])
def test_introspection_resource_bounds(case):
    schema = {"type": "object"}
    if case == "depth":
        for _ in range(70):
            schema = {"type": "object", "properties": {"a": schema}}
    elif case == "paths":
        schema["properties"] = {str(i): {"type": "integer"} for i in range(1001)}
    else:
        schema["allOf"] = [{} for _ in range(10001)]
    with pytest.raises(VerboisyError, match="introspection"):
        SchemaPathIndex.build(schema)


def test_nested_resource_scope_and_policy_cycles():
    schema = {
        "$id": "urn:root",
        "type": "object",
        "properties": {
            "part": {
                "$id": "urn:part",
                "$defs": {"day": {"$anchor": "day", "type": "string", "format": "date"}},
                "type": "object",
                "properties": {"day": {"$ref": "#day"}},
            }
        },
    }
    assert SchemaPathIndex.build(schema).field("/part/day")["format"] == "date"
    schema = {
        "type": "object",
        "properties": {"loop": {"$ref": "#", "x-verboisy-reference-period": "required"}},
    }
    assert SchemaPathIndex.build(schema).unresolved


def test_conditionals_conflicting_annotations_and_path_ambiguity():
    schema = {
        "type": "object",
        "if": {"properties": {"n": {"type": "integer"}}},
        "then": {"properties": {"n": {"type": "integer", "x-verboisy-unit-sensitive": True}}},
        "dependentSchemas": {"n": {"properties": {"other": {"type": "integer"}}}},
    }
    assert "/n" in SchemaPathIndex.build(schema).ambiguous
    conflicting = {
        "type": "object",
        "allOf": [
            {"properties": {"n": {"type": "integer", "format": "date"}}},
            {"properties": {"n": {"type": "string", "format": "time"}}},
        ],
    }
    assert "/n" in SchemaPathIndex.build(conflicting).ambiguous


def test_ambiguous_pattern_fails_safely():
    from types import MappingProxyType

    index = SchemaPathIndex(
        ("a",),
        MappingProxyType({"/a/*/b": {}, "/a/1/*": {}}),
        MappingProxyType({"/a/*/b": (1,), "/a/1/*": (2,)}),
        (),
        (),
    )
    # Specific literal tokens disambiguate ordinary schemas. Two patterns of
    # equal specificity must not silently choose a weaker explicit policy.
    index = SchemaPathIndex(
        ("a",), {"/a/*/1": {}, "/a/1/*": {}}, {"/a/*/1": (1,), "/a/1/*": (2,)}, (), ()
    )
    with pytest.raises(VerboisyError, match="Ambiguous"):
        index.field("/a/1/1")


def test_index_schema_maps_are_immutable():
    index = SchemaPathIndex.build({"type": "object", "properties": {"n": {"type": "integer"}}})
    with pytest.raises(TypeError):
        index.fields["/n"]["type"] = "string"
    with pytest.raises(VerboisyError, match="recursive"):
        validate_research_contract(
            {
                "type": "object",
                "properties": {"loop": {"$ref": "#", "x-verboisy-reference-period": "required"}},
            },
            TaskSpec(),
        )


def test_cycle_with_explicit_root_policy_is_reported():
    index = SchemaPathIndex.build(
        {"type": "object", "$ref": "#", "x-verboisy-reference-period": "required"}
    )
    assert index.unresolved and index.ambiguous


def test_tuple_rest_policy_cannot_apply_to_prefix_items():
    from verboisy.core.fitness import build_field_semantics, semantics_for_pointer

    schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "prefixItems": [{"type": "object"}],
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {
                            "type": "string",
                            "format": "date",
                            "x-verboisy-reference-period": "required",
                        }
                    },
                },
            }
        },
    }
    index = SchemaPathIndex.build(schema)
    assert index.field("/rows/0/day") is None
    assert index.field("/rows/1/day")["format"] == "date"
    semantics = build_field_semantics(schema)
    assert semantics_for_pointer(semantics, "/rows/0/day") is None
    assert semantics_for_pointer(semantics, "/rows/1/day").reference_period == "required"


def test_compatible_allof_bounds_retain_explicit_policy():
    schema = {
        "type": "object",
        "allOf": [
            {
                "properties": {
                    "n": {"type": "integer", "minimum": 0, "x-verboisy-unit-sensitive": True}
                }
            },
            {
                "properties": {
                    "n": {"type": "integer", "minimum": 1, "x-verboisy-unit-sensitive": True}
                }
            },
        ],
    }
    validate_research_contract(schema, TaskSpec())
    assert not SchemaPathIndex.build(schema).ambiguous


def test_required_undeclared_output_id_still_reserves_root_metadata():
    schema = {"type": "array", "items": {"type": "object", "required": ["id"]}}
    assert "id" in SchemaPathIndex.build(schema).properties
    with pytest.raises(VerboisyError, match="id"):
        validate_research_contract(schema, TaskSpec())
