# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Discovery replay failures must precede decisions, display writes and provider work."""

import copy
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from verboisy.api import arun
from verboisy.core import initial_discovery as workflow
from verboisy.core.initial_query_journal import initial_query_journal, replay_initial_query
from verboisy.core.research import ResearchRunner
from verboisy.product import SourcePolicy
from verboisy.storage.changes import pending_change, propose_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_research.test_saved_range_resume_integrity import state
from tests.test_storage.test_change_decisions import OLD, request

OBSERVATION = {
    "provider": "openai",
    "query": "Breed weights",
    "results": [{"title": "Typical weights", "url": "https://example.test/weights"}],
}
ACQUISITION = {"seeds": ["https://example.test/weights"], "observations": [OBSERVATION]}
QUERY = {"query": "Breed weights", "observation": OBSERVATION}
OPTIONS = {"source_policy": {"include": ["example.test"], "avoid": [], "onlyinclude": True}}
BAD_ACQUISITIONS = [
    None,
    [],
    {},
    {"seeds": [], "observations": []},
    {"seeds": [1], "observations": []},
    {"seeds": ["file:///private"], "observations": []},
    {"seeds": ["https://outside.test/"], "observations": []},
    {"seeds": ["https://example.test/"], "observations": None},
    {"seeds": ["https://example.test/"], "observations": [None]},
    {"seeds": ["https://example.test/"], "observations": [{"results": []}]},
    {
        "seeds": ["https://example.test/"],
        "observations": [
            {**OBSERVATION, "results": [{"title": "Other", "url": "https://outside.test/"}]}
        ],
    },
]
BAD_QUERIES = [
    None,
    [],
    {},
    {**QUERY, "query": " "},
    {**QUERY, "query": 1},
    {**QUERY, "observation": None},
    {**QUERY, "observation": {"results": []}},
    {**QUERY, "observation": {"results": [None]}},
    {**QUERY, "observation": {"results": OBSERVATION["results"]}},
    {
        **QUERY,
        "observation": {
            **OBSERVATION,
            "results": [{"title": "Other", "url": "https://outside.test/"}],
        },
    },
]


def create(path, options=OPTIONS):
    with closing(ResearchStore(path)) as store:
        from verboisy.evidence.models import TaskSpec

        rid = store.create("Breed weights", OLD, TaskSpec(), None)
        change = propose_change(store, rid, request())
        store.event(rid, "initial_discovery", {"status": "pending"})
        if options is not None:
            store.event(rid, "product_options", options)
        store.finish(rid, "PAUSED", "proposed_changes", 17, 796)
    return rid, change


async def resume(path, rid, accept, **kwargs):
    return await arun(
        resume=False if accept else rid,
        okresume=rid if accept else False,
        config=Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled"),
        **kwargs,
    )


def forbid_work(monkeypatch):
    from verboisy import api

    discovery = AsyncMock(side_effect=AssertionError("Discovery publication reached"))
    runner = AsyncMock(side_effect=AssertionError("Research reached"))
    monkeypatch.setattr(api, "_initial_discovery", discovery)
    monkeypatch.setattr(ResearchRunner, "run", runner)
    return discovery, runner


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("bad", BAD_ACQUISITIONS)
async def test_saved_acquisition_damage_preserves_pending_decision(
    tmp_path, monkeypatch, accept, bad
):
    path = tmp_path / "run.db"
    rid, change = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_discovery_result", bad)
        before = state(store)
    discovery, runner = forbid_work(monkeypatch)
    with pytest.raises(VerboisyError, match="Saved discovery result failed integrity"):
        await resume(path, rid, accept, mass_unit="lb")
    discovery.assert_not_called()
    runner.assert_not_called()
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
        assert pending_change(store, rid) == change


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("bad", BAD_QUERIES)
async def test_query_damage_preserves_pending_decision(tmp_path, monkeypatch, accept, bad):
    path = tmp_path / "run.db"
    rid, change = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_query_result", bad)
        before = state(store)
    discovery, runner = forbid_work(monkeypatch)
    with pytest.raises(VerboisyError, match="Saved discovery result failed integrity"):
        await resume(path, rid, accept)
    discovery.assert_not_called()
    runner.assert_not_called()
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
        assert pending_change(store, rid) == change


@pytest.mark.parametrize("accept", [False, True])
async def test_conflicting_queries_preserve_pending_decision(tmp_path, monkeypatch, accept):
    path = tmp_path / "run.db"
    rid, change = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_query_result", QUERY)
        other = copy.deepcopy(QUERY)
        other["observation"]["results"][0]["title"] = "Conflicting acquisition"
        store.event(rid, "initial_query_result", other)
        before = state(store)
    forbid_work(monkeypatch)
    with pytest.raises(VerboisyError, match="Saved discovery query has conflicting results"):
        await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
        assert pending_change(store, rid) == change


async def stop(runner, steps):
    runner.store.finish(
        runner.rid,
        "PAUSED",
        "offline_fixture",
        runner.client.total_tokens,
        runner.client.reserved_tokens,
    )
    return "PAUSED", "offline_fixture"


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("options", [None, {}, {"strings": False}, OPTIONS])
async def test_legacy_options_publish_saved_acquisition_without_search(
    tmp_path, monkeypatch, accept, options
):
    path = tmp_path / "run.db"
    rid, _ = create(path, options)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_discovery_result", ACQUISITION)
    monkeypatch.setattr(ResearchRunner, "run", stop)
    search = AsyncMock(side_effect=AssertionError("Paid search reached"))
    monkeypatch.setattr("verboisy.api._discover_seeds", search)
    result = await resume(path, rid, accept)
    assert result.run_id == rid
    search.assert_not_called()
    with closing(ResearchStore(path, read_only=True)) as store:
        assert pending_change(store, rid) is None
        assert len(store.events(rid, "change_decided")) == 1
        assert len(store.events(rid, "seed_frontier")) == 1
        row = store.load(rid)
        assert (row["tokens"], row["reserved"]) == (17, 796)


@pytest.mark.parametrize("accept", [False, True])
async def test_saved_acquisition_takes_precedence_over_bad_older_queries(
    tmp_path, monkeypatch, accept
):
    path = tmp_path / "run.db"
    rid, _ = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_query_result", None)
        store.event(rid, "initial_discovery_result", None)
        store.event(rid, "initial_discovery_result", ACQUISITION)
    monkeypatch.setattr(ResearchRunner, "run", stop)
    await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert len(store.events(rid, "seed_frontier")) == 1


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("kind", ["initial_discovery_result", "initial_query_result"])
async def test_published_frontier_does_not_replay_unused_checkpoints(
    tmp_path, monkeypatch, accept, kind
):
    path = tmp_path / "run.db"
    rid, _ = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, kind, None)
        store.event(rid, "seed_frontier", {"discovered": 0, "active": 0, "deferred": 0})
    monkeypatch.setattr(ResearchRunner, "run", stop)
    discovery = AsyncMock(side_effect=AssertionError("Discovery publication reached"))
    monkeypatch.setattr("verboisy.api._initial_discovery", discovery)
    await resume(path, rid, accept)
    discovery.assert_not_called()


@pytest.mark.parametrize("saved", [False, True])
def test_preflight_restores_enclosing_query_context_without_writing(tmp_path, saved):
    path = tmp_path / "run.db"
    rid, _ = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_query_result", QUERY)
        if saved:
            store.event(rid, "initial_discovery_result", ACQUISITION)
        before = state(store)
        outer = {"payload": {**QUERY, "query": "outer"}}
        writes = []
        with initial_query_journal([outer], writes.append):
            workflow.preflight_initial_discovery(store, rid, SourcePolicy())
            assert replay_initial_query("outer") == OBSERVATION
            assert replay_initial_query("Breed weights") is None
        assert writes == []
        assert state(store) == before


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("options", [{}, OPTIONS])
async def test_valid_query_checkpoint_replays_without_paid_search(
    tmp_path, monkeypatch, accept, options
):
    path = tmp_path / "run.db"
    rid, _ = create(path, options)
    query = copy.deepcopy(QUERY)
    if options:
        query["query"] = "site:example.test Breed weights"
        query["observation"]["query"] = query["query"]
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_query_result", query)
    monkeypatch.setattr(ResearchRunner, "run", stop)
    search = AsyncMock(side_effect=AssertionError("Paid search reached"))
    monkeypatch.setattr("verboisy.api.web_search", search)
    await resume(path, rid, accept)
    search.assert_not_called()
    with closing(ResearchStore(path, read_only=True)) as store:
        assert len(store.events(rid, "initial_discovery_result")) == 1
        assert len(store.events(rid, "seed_frontier")) == 1
        row = store.load(rid)
        assert (row["tokens"], row["reserved"]) == (17, 796)


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("fault", [OSError, RuntimeError, KeyboardInterrupt])
async def test_interrupted_checkpoint_read_preserves_pending_decision(
    tmp_path, monkeypatch, accept, fault
):
    path = tmp_path / "run.db"
    rid, change = create(path)
    with closing(ResearchStore(path)) as store:
        store.event(rid, "initial_discovery_result", ACQUISITION)
        before = state(store)
    original = ResearchStore.events

    def fail(store, run_id, kind=None):
        if kind == "initial_discovery_result":
            raise fault("Checkpoint read interrupted")
        return original(store, run_id, kind)

    monkeypatch.setattr(ResearchStore, "events", fail)
    monkeypatch.setattr(ResearchRunner, "run", stop)
    with pytest.raises(fault, match="Checkpoint read interrupted"):
        await resume(path, rid, accept)
    monkeypatch.setattr(ResearchStore, "events", original)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
        assert pending_change(store, rid) == change


def test_fresh_preflight_leaves_empty_query_context_and_ledger_unchanged(tmp_path):
    path = tmp_path / "run.db"
    rid, _ = create(path)
    with closing(ResearchStore(path)) as store:
        before = state(store)
        workflow.preflight_initial_discovery(store, rid, SourcePolicy())
        assert state(store) == before
        assert replay_initial_query("Breed weights") is None
