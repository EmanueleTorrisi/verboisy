# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Accepted comparable values cannot disappear when unit metadata is absent."""

import copy
from dataclasses import replace

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


@pytest.mark.parametrize("clear_all", [False, True])
def test_missing_metadata_blocks_completion_for_all_accepted_values(tmp_path, clear_all):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        accept_observation(store, rid, task, "persons", name="Beta", revision="second")
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 2})
        assert runner.target_met() is True
        raw = store.evidence(rid)
        events = store.events(rid, "source_fitness")
        for event in events if clear_all else events[-1:]:
            payload = copy.deepcopy(event["payload"])
            payload["claims"] = {}
            store.event(rid, "source_fitness", payload)
        assert len(runner.dataset_comparability_observations()) == 2
        assert runner.target_met() is False
        assert runner.dataset_consistency_gaps() == ("/population:unknown_unit",)
        assert store.evidence(rid) == raw
        assert store.events(rid, "unit_normalization") == []


@pytest.mark.parametrize("flag", ["unit_sensitive", "comparable_across_rows"])
def test_absent_metadata_outside_policy_does_not_block(tmp_path, flag):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        payload = copy.deepcopy(store.events(rid, "source_fitness")[-1]["payload"])
        payload["claims"] = {}
        store.event(rid, "source_fitness", payload)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 1})
        runner.field_semantics["/population"] = replace(
            runner.field_semantics["/population"], **{flag: False}
        )
        assert runner.dataset_comparability_observations() == ()
        assert runner.target_met() is True


def test_missing_nested_array_metadata_uses_concrete_pointer(tmp_path):
    from tests.test_research.test_nested_unit_regressions import (
        accept_observation as accept_nested,
    )
    from tests.test_research.test_nested_unit_regressions import ledger as nested_ledger

    with nested_ledger(tmp_path) as (store, rid, task):
        accept_nested(store, rid, task, "persons")
        accept_nested(store, rid, task, "persons", name="Beta", revision="second")
        payload = copy.deepcopy(store.events(rid, "source_fitness")[-1]["payload"])
        payload["claims"] = {}
        store.event(rid, "source_fitness", payload)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        assert runner.target_met() is False
        observations = runner.dataset_comparability_observations()
        assert len(observations) == 2
        assert {row["pointer"] for row in observations} == {"/population/0"}
        assert runner.dataset_consistency_gaps() == ("/population/*:unknown_unit",)


def test_null_value_without_metadata_does_not_require_a_unit(tmp_path, monkeypatch):
    from tests.test_storage.test_unit_replay_integrity import SCHEMA

    monkeypatch.setitem(SCHEMA["properties"]["population"], "type", ["integer", "null"])
    monkeypatch.setattr(
        "tests.test_storage.test_unit_replay_integrity.ground_source_assessments",
        lambda *_args: {},
    )
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons", population=None)
        payload = copy.deepcopy(store.events(rid, "source_fitness")[-1]["payload"])
        payload["claims"] = {}
        store.event(rid, "source_fitness", payload)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 1})
        assert runner.dataset_comparability_observations() == ()
        assert runner.target_met() is True
