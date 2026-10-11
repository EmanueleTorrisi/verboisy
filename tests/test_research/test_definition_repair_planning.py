# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Row-scoped definition repair planning and bounded, durable source discovery."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


def runner_for(store, rid):
    runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"],
        definition_sensitive=True,
    )
    return runner


@pytest.mark.asyncio
async def test_definition_discovery_is_targeted_bounded_and_durable(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        runner = runner_for(store, rid)
        repairs = runner.dataset_consistency_repairs()
        search = AsyncMock(
            return_value=SearchObservation(
                provider="brave",
                query="fixture",
                results=[
                    SearchResult(title="Metadata", url=f"https://example.test/metadata/{i}")
                    for i in range(5)
                ],
            )
        )
        monkeypatch.setattr("verboisy.core.research.web_search", search)
        raw = store.evidence(rid)
        assert await runner.discover_dataset_repair_source(repairs) is True
        query = search.await_args.args[0]
        assert query == "Alba population definition scope methodology"
        event = store.events(rid, "dataset_repair_discovery")[-1]["payload"]
        assert len(event["queued"]) == 3
        assert event["candidate_key"] == repairs[0]["candidate_key"]
        assert event["snapshot_id"] == repairs[0]["snapshot_id"]
        assert store.evidence(rid) == raw
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        runner = runner_for(reopened, rid)
        assert (
            await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
            is False
        )
        assert search.await_count == 1
    finally:
        reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_definition_discovery_failure_stays_unresolved(tmp_path, monkeypatch, unavailable):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        runner = runner_for(store, rid)
        search = AsyncMock(
            return_value=SearchObservation(provider="brave", query="fixture", results=[])
        )
        if unavailable:
            search.side_effect = SearchUnavailableError("fixture unavailable")
        monkeypatch.setattr("verboisy.core.research.web_search", search)
        assert (
            await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
            is False
        )
        assert runner.dataset_consistency_gaps() == ("/population:unknown_definition",)
        assert store.events(rid, "unit_normalization") == []
        event = store.events(rid, "dataset_repair_discovery")[-1]["payload"]
        assert event["status"] == ("unavailable" if unavailable else "empty")


@pytest.mark.parametrize("missing_unit", [False, True])
def test_definition_request_is_bound_to_affected_row_and_coexists_with_units(
    tmp_path, missing_unit
):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        payload = store.events(rid, "source_fitness")[-1]["payload"]
        payload["claims"]["/population"]["comparability"]["definition"] = {
            "label": "first",
            "source": "revision",
            "quote": "first",
        }
        store.event(rid, "source_fitness", payload)
        accept_observation(
            store,
            rid,
            task,
            "widgets" if missing_unit else "persons",
            name="Beta",
            revision="second",
        )
        before = store.evidence(rid)
        runner = runner_for(store, rid)
        repairs = runner.dataset_consistency_repairs()
        assert [repair["reason"] for repair in repairs] == (
            ["unknown_unit", "unknown_definition"] if missing_unit else ["unknown_definition"]
        )
        repair = repairs[-1]
        assert repair["record_id"] == before[1]["record_id"]
        assert repair["candidate_index"] == 1
        assert repair["pointer"] == "/population"
        assert repair["target_mode"] == "definition"
        assert repair["snapshot_id"] == before[1]["snapshot"]["id"]
        assert repair["candidate_key"]
        assert repair["target_year"] is None
        assert store.evidence(rid) == before
        assert store.events(rid, "unit_normalization") == []


def test_grounded_definition_clears_missing_request_but_different_labels_remain_unresolved(
    tmp_path,
):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        runner = runner_for(store, rid)
        assert len(runner.dataset_consistency_repairs()) == 1
        before = store.records(rid)
        payload = store.events(rid, "source_fitness")[-1]["payload"]
        payload["claims"]["/population"]["comparability"]["definition"] = {
            "label": "first",
            "source": "revision",
            "quote": "first",
        }
        store.event(rid, "source_fitness", payload)
        assert runner.dataset_consistency_repairs() == ()
        assert runner.dataset_consistency_gaps() == ()
        assert store.records(rid) == before
        accept_observation(store, rid, task, "persons", name="Beta", revision="second")
        payload = store.events(rid, "source_fitness")[-1]["payload"]
        payload["claims"]["/population"]["comparability"]["definition"] = {
            "label": "second",
            "source": "revision",
            "quote": "second",
        }
        store.event(rid, "source_fitness", payload)
        assert runner.dataset_consistency_repairs() == ()
        assert runner.dataset_consistency_gaps() == ("/population:unresolved_definitions",)


async def test_unit_and_definition_discovery_have_distinct_durable_attempts(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
        runner = runner_for(store, rid)
        search = AsyncMock(
            return_value=SearchObservation(provider="brave", query="fixture", results=[])
        )
        monkeypatch.setattr("verboisy.core.research.web_search", search)
        repairs = runner.dataset_consistency_repairs()
        for _ in range(3):
            assert await runner.discover_dataset_repair_source(repairs) is False
        assert [call.args[0] for call in search.await_args_list] == [
            "Alba population unit measurement scale",
            "Alba population definition scope methodology",
        ]
        events = store.events(rid, "dataset_repair_discovery")
        assert len({event["payload"]["key"] for event in events}) == 2
