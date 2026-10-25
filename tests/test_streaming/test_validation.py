# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Accelerated decisions must agree with the authoritative JSON Schema validator."""

import copy
import random

import pytest
from verboisy.streaming.validation import row_validator
from verboisy.utils.exceptions import ExtractionError


def test_supported_schemas_match_reference_on_generated_and_boundary_values():
    rng = random.Random(3217)
    atoms = [None, False, True, 0, 1, -1, 1.0, 1.5, "", "東京", [], {}, [1], [True]]
    definitions = [
        *({"type": kind} for kind in ("integer", "number", "string", "null", "boolean")),
        {"type": ["integer", "null"]},
        {"type": "array", "items": {"type": "integer"}},
        {"type": "array", "items": False},
        {"type": "array"},
        {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]},
        {"description": "No assertion keywords"},
        True,
        False,
    ]
    comparisons = 0
    for _ in range(160):
        properties = {name: copy.deepcopy(rng.choice(definitions)) for name in ("a", "b", "")}
        schema = {
            "type": "object",
            "properties": properties,
            "required": rng.sample(["a", "b", "", "outside"], rng.randrange(5)),
            "additionalProperties": rng.choice([True, False]),
        }
        validator = row_validator(schema)
        assert validator.compiled is not None
        values = list(atoms)
        values += [
            {
                key: copy.deepcopy(rng.choice(atoms))
                for key in rng.sample(["a", "b", "", "outside"], rng.randrange(5))
            }
            for _ in range(70)
        ]
        for value in values:
            before = copy.deepcopy(value)
            assert validator.is_valid(value) == validator.reference.is_valid(value)
            assert value == before
            comparisons += 1
    assert comparisons == 13440


@pytest.mark.parametrize(
    "definition",
    [
        {"type": "integer", "minimum": 2},
        {"type": "number", "multipleOf": 0.1},
        {"type": "string", "format": "date"},
        {"type": "string", "pattern": "^a+$"},
        {"type": "array", "uniqueItems": True},
        {"type": "array", "items": {"const": 2}},
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "object", "minProperties": 1},
        {"type": ["object", "null"], "required": ["x"]},
        {"enum": [None, 1, True]},
        {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        {"properties": {"x": {"type": "integer"}}},
        {"type": "string", "x-future-keyword": True},
    ],
)
def test_other_keywords_use_the_complete_reference_validator(definition):
    validator = row_validator({"type": "object", "properties": {"a": definition}})
    assert validator.compiled is None
    for value in [None, True, 1, 2, 0.3, "bad", "2024-02-30", "aaa", {}, {"x": "2"}, [1, 1], [2]]:
        record = {"a": value}
        assert validator.is_valid(record) == validator.reference.is_valid(record)


def test_root_array_keeps_local_reference_context_and_type_semantics():
    referenced = row_validator(
        {
            "type": "array",
            "$defs": {"n": {"type": "integer", "minimum": 1}},
            "items": {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}},
        }
    )
    assert referenced.compiled is None
    assert referenced.is_valid({"n": 1}) and not referenced.is_valid({"n": 0})
    fast = row_validator(
        {"type": "array", "items": {"type": "object", "properties": {"n": {"type": "integer"}}}}
    )
    assert fast.compiled is not None
    assert fast.is_valid({"n": 1.0})
    assert not fast.is_valid({"n": True})
    assert not fast.is_valid({"n": 1.5})


def test_original_schema_mutation_does_not_change_compiled_contract():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
        "additionalProperties": False,
    }
    validator = row_validator(schema)
    schema["required"].clear()
    schema["properties"]["n"]["type"] = "string"
    schema["additionalProperties"] = True
    assert validator.is_valid({"n": 1})
    for value in [{}, {"n": "1"}, {"n": 1, "extra": 2}]:
        assert not validator.is_valid(value)


def test_compiler_limits_fall_back_without_dropping_validation():
    wide = {"type": "object", "properties": {str(i): {"type": "integer"} for i in range(520)}}
    validator = row_validator(wide)
    assert validator.compiled is None
    assert not validator.is_valid({"519": "bad"})
    nested = {"type": "integer"}
    value = "bad"
    for _ in range(34):
        nested = {"type": "array", "items": nested}
        value = [value]
    validator = row_validator({"type": "object", "properties": {"a": nested}})
    assert validator.compiled is None and not validator.is_valid({"a": value})


@pytest.mark.parametrize(
    "definition", [{"type": "invented"}, {"type": []}, {"type": [1]}, {"required": "a"}]
)
def test_invalid_schemas_are_rejected_before_compilation(definition):
    with pytest.raises(ExtractionError):
        row_validator({"type": "object", "properties": {"a": definition}})
