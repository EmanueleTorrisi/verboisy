# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Transient repair discovery retries are bounded across SQLite reopen."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


def runner_for(store, rid, kind):
    runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"],
        definition_sensitive=kind == "definition",
    )
    return runner


@pytest.mark.parametrize("kind", ["unit", "definition"])
async def test_unavailable_retries_after_reopen_then_success_is_durable(
    tmp_path, monkeypatch, kind
):
    search = AsyncMock(
        side_effect=[
            SearchUnavailableError("temporary outage"),
            SearchObservation(
                provider="brave",
                query="fixture",
                results=[
                    SearchResult(title="Metadata", url="https://example.test/metadata"),
                ],
            ),
        ]
    )
    monkeypatch.setattr("verboisy.core.research.web_search", search)
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets" if kind == "unit" else "persons")
        runner = runner_for(store, rid, kind)
        repairs = runner.dataset_consistency_repairs()
        assert await runner.discover_dataset_repair_source(repairs) is False
        assert await runner.discover_dataset_repair_source(repairs) is False
        assert search.await_count == 1
        before = store.evidence(rid)
    for expected in (True, False):
        store = ResearchStore(str(tmp_path / "replay.db"))
        try:
            runner = runner_for(store, rid, kind)
            assert (
                await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
                is expected
            )
            assert store.evidence(rid) == before
            assert runner.dataset_consistency_gaps() == (f"/population:unknown_{kind}",)
        finally:
            store.close()
    assert search.await_count == 2


@pytest.mark.parametrize("kind", ["unit", "definition"])
async def test_persistent_outage_stops_after_three_total_attempts(tmp_path, monkeypatch, kind):
    search = AsyncMock(side_effect=SearchUnavailableError("persistent outage"))
    monkeypatch.setattr("verboisy.core.research.web_search", search)
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets" if kind == "unit" else "persons")
    for invocation in range(5):
        store = ResearchStore(str(tmp_path / "replay.db"))
        try:
            runner = runner_for(store, rid, kind)
            repairs = runner.dataset_consistency_repairs()
            assert await runner.discover_dataset_repair_source(repairs) is False
            assert await runner.discover_dataset_repair_source(repairs) is False
            assert search.await_count == min(invocation + 1, 3)
            assert len(store.events(rid, "dataset_repair_discovery")) == min(invocation + 1, 3)
        finally:
            store.close()


async def test_empty_result_after_outage_is_terminal(tmp_path, monkeypatch):
    search = AsyncMock(
        side_effect=[
            SearchUnavailableError("temporary outage"),
            SearchObservation(provider="brave", query="fixture", results=[]),
        ]
    )
    monkeypatch.setattr("verboisy.core.research.web_search", search)
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
    for _ in range(3):
        store = ResearchStore(str(tmp_path / "replay.db"))
        try:
            runner = runner_for(store, rid, "unit")
            assert (
                await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
                is False
            )
        finally:
            store.close()
    assert search.await_count == 2
