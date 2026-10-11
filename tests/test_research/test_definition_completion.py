# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from dataclasses import replace

import pytest
from verboisy.core.fitness import FieldSemantics, dataset_definition_consistency_errors
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


@pytest.mark.parametrize(
    ("second_definition", "expected", "expected_gaps"),
    [
        ("resident population", True, ()),
        ("registered population", False, ("/population:unresolved_definitions",)),
        (None, False, ("/population:unknown_definition",)),
        ("Resident population", False, ("/population:unresolved_definitions",)),
    ],
)
def test_definition_completion_uses_grounded_accepted_evidence(
    tmp_path, second_definition, expected, expected_gaps
):
    with ledger(tmp_path) as (store, rid, task):
        for name, definition in [("Alba", "resident population"), ("Beta", second_definition)]:
            revision = name + ": " + (definition or "definition unavailable")
            accept_observation(store, rid, task, "persons", name=name, revision=revision)
            row = store.evidence(rid)[-1]
            candidate = Candidate.model_validate(row["candidate"])
            page = Snapshot.model_validate(row["snapshot"])
            assessment = {
                "pointer": "/population",
                "unit": {
                    "label": "persons",
                    "citation": {
                        "source": "unit",
                        "quote": "Population unit: persons.",
                    },
                },
            }
            if definition is not None:
                assessment["definition"] = {
                    "label": definition,
                    "citation": {
                        "source": "revision",
                        "quote": revision,
                    },
                }
            response = SourceAssessmentResponse.model_validate({"assessments": [assessment]})
            claims = ground_source_assessments(candidate, page, response)
            store.event(
                rid,
                "source_fitness",
                source_fitness_event(
                    page,
                    candidate,
                    claims,
                    cache_key="definition-fixture",
                    cache_hit=False,
                ),
            )
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task.target_records = 2
        runner.field_semantics["/population"] = replace(
            runner.field_semantics["/population"],
            definition_sensitive=True,
        )
        original = store.evidence(rid)
        actual = runner.target_met()
        assert actual is expected
        assert runner.dataset_consistency_gaps() == expected_gaps
        assert store.evidence(rid) == original
        assert store.events(rid, "unit_normalization") == []


@pytest.mark.parametrize(
    "descriptor", [None, {}, {"label": None}, {"label": 3}, {"label": ""}, {"label": "  "}]
)
def test_missing_or_malformed_definition_is_unknown(descriptor):
    semantics = {
        "/value": FieldSemantics(
            pointer="/value", definition_sensitive=True, comparable_across_rows=True
        )
    }
    observations = ({"pointer": "/value", "definition": descriptor},)
    assert dataset_definition_consistency_errors(observations, semantics) == (
        "/value:unknown_definition",
    )


@pytest.mark.parametrize(
    "case", ["missing_pointer", "unknown_field", "not_sensitive", "not_comparable"]
)
def test_definition_policy_scope(case):
    semantics = {
        "/value": FieldSemantics(
            pointer="/value",
            definition_sensitive=case != "not_sensitive",
            comparable_across_rows=case != "not_comparable",
        )
    }
    pointer = (
        None if case == "missing_pointer" else "/other" if case == "unknown_field" else "/value"
    )
    assert dataset_definition_consistency_errors(({"pointer": pointer},), semantics) == ()


def test_definition_arrays_and_multiple_gaps():
    semantics = {
        "/values/*": FieldSemantics(
            pointer="/values/*", definition_sensitive=True, comparable_across_rows=True
        )
    }
    observations = tuple(
        {"pointer": "/values/" + str(i), "definition": {"label": label}}
        for i, label in enumerate(["resident", "registered", ""])
    )
    assert dataset_definition_consistency_errors(observations, semantics) == (
        "/values/*:unknown_definition",
        "/values/*:unresolved_definitions",
    )


@pytest.mark.parametrize("null_value", [False, True])
def test_definition_only_policy_covers_missing_metadata_and_ignores_null(
    tmp_path, monkeypatch, null_value
):
    from tests.test_storage.test_unit_replay_integrity import SCHEMA

    monkeypatch.setitem(SCHEMA["properties"]["population"], "type", ["integer", "null"])
    monkeypatch.setattr(
        "tests.test_storage.test_unit_replay_integrity.ground_source_assessments", lambda *_args: {}
    )
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons", population=None if null_value else 2)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task.target_records = 1
        runner.field_semantics["/population"] = replace(
            runner.field_semantics["/population"], unit_sensitive=False, definition_sensitive=True
        )
        assert runner.target_met() is null_value
        assert runner.dataset_consistency_gaps() == (
            () if null_value else ("/population:unknown_definition",)
        )
