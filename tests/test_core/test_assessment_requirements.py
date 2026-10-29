# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Completion requirements reach assessment without becoming source evidence."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.core.fitness import FieldSemantics
from verboisy.core.source_assessment import (
    SOURCE_ASSESSMENT_CACHE_VERSION,
    assess_source_batch,
    assessment_requirements,
    cached_source_assessment,
    ground_source_assessment_batch,
    source_assessment_cache_key,
)
from verboisy.evidence.models import Candidate

from tests.test_core.test_source_assessment import candidate, page


def semantics(**changes):
    return {
        "/population": FieldSemantics(pointer="/population", comparable_across_rows=True, **changes)
    }


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, {}),
        ({"unit_sensitive": True}, {"/population": ["unit"]}),
        ({"definition_sensitive": True}, {"/population": ["definition"]}),
        ({"methodology_sensitive": True}, {"/population": ["methodology_identity"]}),
        (
            {"unit_sensitive": True, "definition_sensitive": True, "methodology_sensitive": True},
            {"/population": ["unit", "definition", "methodology_identity"]},
        ),
    ],
)
async def test_assessment_receives_requirements_and_keeps_absent_metadata_absent(flags, expected):
    client = SimpleNamespace(
        complete_json=AsyncMock(
            return_value={"candidates": [{"candidate_index": 0, "assessments": []}]}
        )
    )
    record = candidate()
    original = record.model_dump()
    result = await assess_source_batch(
        client,
        goal="Compare populations",
        page=page(),
        candidates=[record],
        field_semantics=semantics(**flags),
    )
    payload = json.loads(client.complete_json.await_args.args[1])
    assert payload["candidates"][0]["required_comparability"] == expected
    assert payload["candidates"][0]["scope"] == record.scope
    assert "other" not in {source["id"] for source in payload["sources"]}
    assert record.model_dump() == original
    claims = ground_source_assessment_batch([record], page(), result)[0]
    assert claims["/population"].comparability is None
    assert not claims["/population"].grounded
    client.complete_json.assert_awaited_once()


def test_requirements_respect_nulls_noncomparable_fields_and_concrete_array_pointers():
    record = Candidate(
        scope="s1",
        evidence={},
        record={"values": [0, None, 2], "ignored": 3, "unknown": 4},
    )
    policy = {
        "/values/*": FieldSemantics(
            pointer="/values/*", comparable_across_rows=True, unit_sensitive=True
        ),
        "/ignored": FieldSemantics(pointer="/ignored", unit_sensitive=True),
    }
    assert assessment_requirements([record], policy) == [
        {"/values/0": ["unit"], "/values/2": ["unit"]}
    ]
    assert assessment_requirements([record], None) == [{}]
    assert assessment_requirements([], policy) == []


def test_assessment_cache_tracks_effective_requirements_and_rejects_old_protocol():
    record, snapshot = candidate(), page()
    unit = semantics(unit_sensitive=True)
    before = source_assessment_cache_key(snapshot, [record])
    after = source_assessment_cache_key(snapshot, [record], field_semantics=unit)
    assert before != after
    changed = semantics(unit_sensitive=True, definition_sensitive=True)
    assert after != source_assessment_cache_key(snapshot, [record], field_semantics=changed)
    same = {**unit, "/absent": FieldSemantics(pointer="/absent", unit_sensitive=True)}
    assert after == source_assessment_cache_key(snapshot, [record], field_semantics=same)
    disabled = {key: replace(value, comparable_across_rows=False) for key, value in unit.items()}
    assert before == source_assessment_cache_key(snapshot, [record], field_semantics=disabled)
    event = {
        "kind": "source_assessment_cache",
        "payload": {
            "version": SOURCE_ASSESSMENT_CACHE_VERSION - 1,
            "key": after,
            "response": {"candidates": []},
        },
    }
    assert cached_source_assessment([event], after) is None
