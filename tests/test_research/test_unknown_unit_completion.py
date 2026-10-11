# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Unknown units block comparable dataset completion without implying incompatibility."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


@pytest.mark.parametrize(
    "first_unit,second_unit,expected_gap",
    [
        ("persons", "persons", None),
        ("persons", "widgets", "unknown_unit"),
        ("widgets", "widgets", "unknown_unit"),
        ("persons", "kg", "incompatible_units"),
        ("thousands of persons", "persons", None),
    ],
)
def test_real_store_unit_completion(tmp_path, first_unit, second_unit, expected_gap):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, first_unit)
        accept_observation(store, rid, task, second_unit, name="Beta", revision="second")
        before = store.evidence(rid)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 2})
        assert runner.target_met() is (expected_gap is None)
        assert runner.dataset_consistency_gaps() == (
            () if expected_gap is None else (f"/population:{expected_gap}",)
        )
        assert store.evidence(rid) == before


@pytest.mark.asyncio
async def test_unknown_unit_run_pauses_with_explicit_diagnostic(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        accept_observation(store, rid, task, "widgets", name="Beta", revision="second")
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 2})
        runner.browser = AsyncMock()
        assert await runner.run(1) == ("PAUSED", "dataset_consistency_gaps")
        event = store.events(rid, "dataset_consistency_gap")[-1]["payload"]
        assert event["gaps"] == ["/population:unknown_unit"]
        assert store.events(rid, "unit_normalization") == []


@pytest.mark.parametrize("flag", ["unit_sensitive", "comparable_across_rows"])
def test_unknown_units_do_not_block_fields_outside_policy(tmp_path, flag):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.task = runner.task.model_copy(update={"target_records": 1})
        runner.field_semantics["/population"] = replace(
            runner.field_semantics["/population"], **{flag: False}
        )
        assert runner.target_met() is True
        assert runner.dataset_consistency_gaps() == ()
