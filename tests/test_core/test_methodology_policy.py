# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Methodology policy is explicit, durable and compatible with older plans."""

import pytest
from verboisy.core.fitness import build_field_semantics, scalar_field_schemas
from verboisy.core.planner import TemporalIntent
from verboisy.core.semantic_planner import (
    _validate_semantic_response_contract,
    semantic_plan_event,
    semantic_plan_from_event,
)
from verboisy.utils.exceptions import LLMResponseError


def schema_for(value):
    return {
        "type": "object",
        "properties": {
            "measure": {
                "type": "number",
                "x-verboisy-methodology-sensitive": value,
            }
        },
    }


def event_for(schema):
    return semantic_plan_event(
        build_field_semantics(schema),
        research_year=2026,
        temporal_intent=TemporalIntent(mode="latest"),
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_methodology_policy_round_trips(enabled):
    schema = schema_for(enabled)
    event = event_for(schema)
    assert event["fields"][0]["methodology_sensitive"] is enabled
    _, _, restored = semantic_plan_from_event(event, schema=schema)
    assert restored["/measure"].methodology_sensitive is enabled
    assert restored["/measure"].basis == "explicit"


def test_legacy_plan_defaults_to_no_methodology_requirement():
    schema = {"type": "object", "properties": {"measure": {"type": "number"}}}
    event = event_for(schema)
    del event["fields"][0]["methodology_sensitive"]
    _, _, restored = semantic_plan_from_event(event, schema=schema)
    assert restored["/measure"].methodology_sensitive is False


@pytest.mark.parametrize("explicit", [None, False, True])
def test_model_policy_cannot_override_explicit_methodology(explicit):
    schema = schema_for(explicit)
    if explicit is None:
        del schema["properties"]["measure"]["x-verboisy-methodology-sensitive"]
    proposal = event_for(schema)["fields"][0]
    del proposal["basis"]
    proposal["methodology_sensitive"] = explicit is not True
    result = _validate_semantic_response_contract(
        {"fields": [proposal]},
        baseline=build_field_semantics(schema),
        field_schemas=scalar_field_schemas(schema),
    )
    assert result["/measure"].methodology_sensitive is (True if explicit is None else explicit)


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_nonboolean_methodology_policy_is_rejected(invalid):
    schema = schema_for(False)
    event = event_for(schema)
    event["fields"][0]["methodology_sensitive"] = invalid
    with pytest.raises(ValueError, match="invalid persisted semantic plan"):
        semantic_plan_from_event(event, schema=schema)
    proposal = event["fields"][0]
    del proposal["basis"]
    with pytest.raises(LLMResponseError):
        _validate_semantic_response_contract(
            {"fields": [proposal]},
            baseline=build_field_semantics(schema),
            field_schemas=scalar_field_schemas(schema),
        )
