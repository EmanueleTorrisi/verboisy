# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Row-scoped unit repair planning and bounded, durable source discovery."""

import copy
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


def runner_for(store, rid):
    return ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))


@pytest.mark.parametrize("missing", [False, True])
def test_unit_repair_identifies_only_the_affected_row(tmp_path, missing):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        accept_observation(
            store, rid, task, "persons" if missing else "widgets", name="Beta", revision="second"
        )
        if missing:
            payload = copy.deepcopy(store.events(rid, "source_fitness")[-1]["payload"])
            payload["claims"] = {}
            store.event(rid, "source_fitness", payload)
        raw = store.evidence(rid)
        repairs = runner_for(store, rid).dataset_consistency_repairs()
        assert len(repairs) == 1
        repair = repairs[0]
        assert repair["candidate_index"] == 1
        assert repair["record_id"] == raw[1]["record_id"]
        assert repair["snapshot_id"] == raw[1]["snapshot"]["id"]
        assert repair["candidate_key"]
        assert repair["pointer"] == "/population"
        assert repair["reason"] == "unknown_unit"
        assert repair["target_mode"] == "unit"
        assert repair["target_year"] is None
        assert store.evidence(rid) == raw
        assert store.events(rid, "unit_normalization") == []


@pytest.mark.asyncio
async def test_unit_discovery_is_targeted_bounded_and_durable(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
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
        assert query == "Alba population unit measurement scale"
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
async def test_unit_discovery_failure_stays_unresolved(tmp_path, monkeypatch, unavailable):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
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
        assert runner.dataset_consistency_gaps() == ("/population:unknown_unit",)
        assert store.events(rid, "unit_normalization") == []
        event = store.events(rid, "dataset_repair_discovery")[-1]["payload"]
        assert event["status"] == ("unavailable" if unavailable else "empty")


def test_grounded_metadata_removes_repair_without_changing_value(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        grounded = copy.deepcopy(store.events(rid, "source_fitness")[-1]["payload"])
        missing = copy.deepcopy(grounded)
        missing["claims"] = {}
        store.event(rid, "source_fitness", missing)
        runner = runner_for(store, rid)
        before = store.records(rid)
        assert len(runner.dataset_consistency_repairs()) == 1
        store.event(rid, "source_fitness", grounded)
        assert runner.dataset_consistency_repairs() == ()
        assert runner.dataset_consistency_gaps() == ()
        assert store.records(rid) == before
