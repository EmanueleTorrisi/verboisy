# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Regression tests for advertised JSON Schema behavior."""

import pytest
from pydantic import ValidationError
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.utils.exceptions import ExtractionError


def build(shape):
    return SchemaBuilder.build_model("Target", shape)


@pytest.mark.parametrize(
    "definition,invalid",
    [
        ({"type": "integer"}, "3"),
        ({"type": "integer"}, True),
        ({"type": "number", "minimum": 2}, 1),
        ({"type": "string", "enum": ["ok"]}, "other"),
        ({"type": "string", "pattern": "^A"}, "Bob"),
        ({"type": "array", "items": {"type": "integer"}}, [1, "2"]),
        ({"type": "object", "required": ["x"]}, {}),
        ({"type": "string", "format": "uri"}, "Website"),
    ],
)
def test_constraints_and_no_coercion(definition, invalid):
    model = build(
        {
            "type": "array",
            "items": {"type": "object", "properties": {"value": definition}, "required": ["value"]},
        }
    )
    with pytest.raises(ValidationError):
        model.model_validate({"value": invalid})


def test_nested_local_ref():
    schema = {
        "type": "array",
        "$defs": {"amount": {"type": "number", "minimum": 0}},
        "items": {"type": "object", "properties": {"cost": {"$ref": "#/$defs/amount"}}},
    }
    model = build(schema)
    assert model.model_validate({"cost": 4}).model_dump(exclude_unset=True) == {"cost": 4}
    with pytest.raises(ValidationError):
        model.model_validate({"cost": -1})


def test_optional_omission_differs_from_null():
    model = build({"type": "object", "properties": {"name": {"type": "string"}}})
    assert model.model_validate({}).model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        model.model_validate({"name": None})


def test_nullable_and_extra_properties():
    model = build(
        {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
            "additionalProperties": False,
        }
    )
    assert model.model_validate({"name": None}).name is None
    with pytest.raises(ValidationError):
        model.model_validate({"extra": "value"})


def test_json_keys_survive_model_names():
    model = build(
        {"properties": {"model_dump": {"type": "string"}, "unit-price": {"type": "number"}}}
    )
    row = {"model_dump": "value", "unit-price": 3}
    assert model.model_validate(row).model_dump(by_alias=True, exclude_unset=True) == row


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "integer"},
        {"type": "object", "required": 42},
        {"type": "object", "$ref": "https://example.com/schema"},
        {"type": "object", "$ref": "file:///tmp/schema"},
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"},
    ],
)
def test_reject_invalid_or_unsupported_schemas(schema):
    with pytest.raises(ExtractionError):
        build(schema)


def test_reject_nonfinite_number():
    model = build({"properties": {"n": {"type": "number"}}})
    with pytest.raises(ValidationError):
        model.model_validate({"n": float("nan")})


def test_reference_named_properties_and_literal_defaults():
    model = build(
        {
            "type": "object",
            "properties": {
                "$ref": {"type": "string"},
                "payload": {"type": "object", "default": {"$ref": "https://literal.example"}},
                "model_dump": {"type": "string"},
                "field_0": {"type": "string"},
            },
        }
    )
    value = {"$ref": "literal", "model_dump": "x", "field_0": "y"}
    assert model.model_validate(value).model_dump(by_alias=True, exclude_unset=True) == value


@pytest.mark.parametrize(
    "schema",
    [
        None,
        [],
        "not a schema",
    ],
)
def test_normalize_rejects_non_object_schema(schema):
    """The schema itself must be a JSON object."""
    with pytest.raises(
        ExtractionError,
        match="Schema must be a JSON object",
    ):
        SchemaBuilder.normalize(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": [],
        },
        {
            "type": "object",
            "allOf": {},
        },
    ],
)
def test_reject_invalid_schema_keyword_containers(schema):
    """Reject schema-bearing keywords with incorrect container types."""
    with pytest.raises(
        ExtractionError,
        match="Invalid JSON Schema",
    ):
        SchemaBuilder.normalize(schema)


def test_references_inside_allof_are_checked():
    """Reject external references nested inside composition keywords."""
    schema = {
        "type": "object",
        "allOf": [
            {
                "$ref": "https://example.com/external-schema",
            }
        ],
    }

    with pytest.raises(
        ExtractionError,
        match="Only local fragment schema references are supported",
    ):
        SchemaBuilder.normalize(schema)


@pytest.mark.asyncio
async def test_extractor_rejects_missing_required_temporal_evidence():
    from unittest.mock import AsyncMock

    from verboisy.core.planner import TemporalIntent
    from verboisy.evidence.models import (
        Candidate,
        Proof,
        Snapshot,
        Source,
        TaskSpec,
    )
    from verboisy.extractor.evidenced import EvidenceExtractor

    schema = {
        "type": "object",
        "properties": {
            "population": {
                "type": "integer",
                "x-verboisy-temporal-class": "mutable",
                "x-verboisy-reference-period": "required",
            }
        },
        "required": ["population"],
    }

    client = AsyncMock()

    extractor = EvidenceExtractor(
        client,
        schema,
        TaskSpec(),
        "Find the latest population",
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-09-30T00:00:00Z",
        content_hash="hash",
        sources=[
            Source(
                id="e1",
                kind="text",
                text="41000000",
                scope="s1",
            )
        ],
        truncated=False,
    )

    candidate = Candidate(
        scope="s1",
        record={"population": 41_000_000},
        evidence={
            "/population": Proof(
                source="e1",
                quote="41000000",
                transform="integer",
            )
        },
    )

    assert await extractor.check(
        candidate,
        page,
    ) == ["/population:" "missing_temporal_evidence"]

    client.complete_json.assert_not_awaited()
