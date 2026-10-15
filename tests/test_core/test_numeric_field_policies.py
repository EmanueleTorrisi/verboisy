# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Numeric object names and restored plans resolve their declared scalar policies."""

from verboisy.core.fitness import build_field_semantics, semantics_for_pointer
from verboisy.core.planner import TemporalIntent
from verboisy.core.semantic_planner import semantic_plan_event, semantic_plan_from_event


def test_numeric_keys_arrays_and_plan_restore():
    schema = {
        "type": "object",
        "properties": {
            "2024": {"type": "integer", "x-verboisy-unit-sensitive": True},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "2024": {"type": "integer", "x-verboisy-definition-sensitive": True}
                    },
                },
            },
        },
    }
    semantics = build_field_semantics(schema)
    assert semantics_for_pointer(semantics, "/2024").unit_sensitive
    assert semantics_for_pointer(semantics, "/rows/3/2024").definition_sensitive
    assert semantics_for_pointer(semantics, "/2025") is None
    event = semantic_plan_event(
        semantics, research_year=2026, temporal_intent=TemporalIntent(mode="latest")
    )
    assert all("array_positions" not in item for item in event["fields"])
    _, _, restored = semantic_plan_from_event(event, schema=schema)
    assert semantics_for_pointer(restored, "/rows/3/2024").pointer == "/rows/*/2024"


def test_required_temporal_policy_for_numeric_object_key():
    import pytest
    from verboisy.core.fitness import FieldSemantics, temporal_errors
    from verboisy.evidence.models import Candidate
    from verboisy.evidence.snapshot import snapshot
    from verboisy.utils.exceptions import VerboisyError

    schema = {
        "type": "object",
        "properties": {"2024": {"type": "integer", "x-verboisy-reference-period": "required"}},
    }
    page = snapshot("<p>42</p>", "https://example.test/")
    errors = temporal_errors(
        Candidate(scope="page", record={"2024": 42}, evidence={}),
        page,
        schema,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )
    assert any("/2024" in error and "temporal" in error for error in errors)
    ambiguous = {
        "/a/*/1": FieldSemantics("/a/*/1", array_positions=(1,)),
        "/a/1/*": FieldSemantics("/a/1/*", array_positions=(2,)),
    }
    with pytest.raises(VerboisyError, match="Ambiguous"):
        semantics_for_pointer(ambiguous, "/a/1/1")
