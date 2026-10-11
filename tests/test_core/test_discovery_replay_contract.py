# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved acquisition replay must validate shape and scope before publishing work."""

import copy
import json
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from verboisy.core.discovery_replay import validated_discovery_result
from verboisy.core.initial_discovery import discover_seed_sources, publish_initial_discovery
from verboisy.core.initial_query_journal import initial_query_journal, replay_initial_query
from verboisy.core.planner import build_research_plan
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.llm.client import LLMClient
from verboisy.product import SourcePolicy
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

URL = "https://allowed.test/a"
OBSERVATION = {"provider": "brave", "query": "query", "results": [{"title": "Source", "url": URL}]}
BAD_OBSERVATIONS = [
    [],
    {},
    {**OBSERVATION, "provider": "unknown"},
    {**OBSERVATION, "results": [{"url": URL}]},
    {**OBSERVATION, "results": [{"title": "Source", "url": "file:///private"}]},
    {**OBSERVATION, "results": [{"title": "Source", "url": "https://outside.test/"}]},
]
CASES = [
    (seeds, [])
    for seeds in [
        None,
        [],
        URL,
        [None],
        ["file:///private"],
        ["https://user:secret@allowed.test/"],
        ["https://allowed.test/with space"],
        ["https://allowed.test/\\unsafe"],
        ["https://allowed.test:bad/"],
        ["https://outside.test/"],
        ["https://blocked.allowed.test/"],
    ]
]
CASES += [
    ([URL], observations)
    for observations in [
        None,
        {},
        [None],
        [{**OBSERVATION, "provider": "unknown"}],
        [{**OBSERVATION, "results": [{"url": URL}]}],
        [{**OBSERVATION, "results": [{"title": "Source", "url": "file:///private"}]}],
        [{**OBSERVATION, "results": [{"title": "Source", "url": "https://outside.test/"}]}],
    ]
]


def policy():
    return SourcePolicy(
        include=("allowed.test",), avoid=("blocked.allowed.test",), onlyinclude=True
    )


def config():
    return Settings(_env_file=None, search_provider="disabled")


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("seeds,observations", CASES)
async def test_invalid_acquisition_does_not_publish_task_or_frontier(
    tmp_path, cached, seeds, observations
):
    with closing(ResearchStore(tmp_path / "discovery.db")) as store:
        spec = TaskSpec()
        rid = store.create("Goal", {"type": "object"}, spec, None)
        store.finish(rid, "RUNNING", "fixture", 9, 17)
        if cached:
            store.event(
                rid, "initial_discovery_result", {"seeds": seeds, "observations": observations}
            )
        before_task = store.load(rid)["task_json"]
        before_events = store.events(rid)
        discover = (
            AsyncMock(side_effect=AssertionError("paid discovery repeated"))
            if cached
            else AsyncMock(return_value=(seeds, observations))
        )
        with pytest.raises(VerboisyError) as caught:
            await publish_initial_discovery(
                store,
                rid,
                spec,
                policy(),
                config(),
                build_research_plan({"type": "object"}, None),
                discover,
                LLMClient,
            )
        assert caught.value.details["run_id"] == rid
        assert "secret" not in str(caught.value)
        state = store.load(rid)
        assert state["task_json"] == before_task
        assert (state["status"], state["reason"]) == ("PAUSED", "source_discovery_failed")
        assert (state["tokens"], state["reserved"]) == (9, 17)
        assert store.pages(rid) == []
        assert store.events(rid) == before_events
        assert discover.await_count == (0 if cached else 1)


@pytest.mark.parametrize("observation", BAD_OBSERVATIONS)
async def test_invalid_cached_query_is_not_replaced_by_paid_search(observation):
    query = "site:allowed.test Goal"
    events = [{"payload": {"query": query, "observation": observation}}]
    search = AsyncMock(side_effect=AssertionError("paid search repeated"))
    with (
        pytest.raises(VerboisyError, match="discovery result failed integrity"),
        initial_query_journal(events, lambda _: pytest.fail("journal write")),
    ):
        await discover_seed_sources(
            "Goal",
            TaskSpec(),
            policy(),
            config(),
            build_research_plan({"type": "object"}, None),
            search,
            lambda _: [],
            canonical_url,
        )
    assert search.await_count == 0
    assert replay_initial_query(query) is None


@pytest.mark.parametrize("value", [None, [], {}, {"seeds": [URL]}])
def test_invalid_saved_result_shape_has_controlled_error(value):
    with pytest.raises(VerboisyError, match="discovery result failed integrity"):
        validated_discovery_result(value, policy(), canonicalize=canonical_url)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("onlyinclude", [False, True])
async def test_valid_replay_preserves_history_and_publishes_canonical_order(
    tmp_path, cached, onlyinclude
):
    with closing(ResearchStore(tmp_path / "valid.db")) as store:
        spec = TaskSpec()
        rid = store.create("Goal", {"type": "object"}, spec, None)
        store.finish(rid, "RUNNING", "fixture", 9, 17)
        observation = {**OBSERVATION, "historical_note": "retained"}
        seeds = ["HTTPS://ALLOWED.TEST:443/a#section", URL, "https://allowed.test/b"]
        acquisition = {"seeds": seeds, "observations": [observation]}
        original = copy.deepcopy(acquisition)
        if cached:
            store.event(rid, "initial_discovery_result", acquisition)
        discover = (
            AsyncMock(side_effect=AssertionError("paid discovery repeated"))
            if cached
            else AsyncMock(return_value=(seeds, [observation]))
        )
        result = await publish_initial_discovery(
            store,
            rid,
            spec,
            SourcePolicy(include=("allowed.test",), onlyinclude=onlyinclude),
            config(),
            build_research_plan({"type": "object"}, None),
            discover,
            LLMClient,
        )
        assert result.seed_urls == [URL, "https://allowed.test/b"]
        assert json.loads(store.load(rid)["task_json"])["seed_urls"] == result.seed_urls
        assert [row["url"] for row in store.pages(rid)] == result.seed_urls
        assert store.events(rid, "source_discovery")[0]["payload"] == observation
        assert store.events(rid, "initial_discovery_result")[0]["payload"] == (
            original if cached else {"seeds": result.seed_urls, "observations": [observation]}
        )
        assert acquisition == original
        assert (store.load(rid)["tokens"], store.load(rid)["reserved"]) == (9, 17)
        assert discover.await_count == (0 if cached else 1)


@pytest.mark.parametrize(
    "unsafe",
    [
        "file://allowed.test/private",
        "https://user:secret@allowed.test/",
        "https://allowed.test:bad/",
        "https://allowed.test/with space",
    ],
)
async def test_fresh_mixed_search_keeps_permitted_sources(unsafe):
    from verboisy.core.search import SearchObservation, SearchResult

    search = AsyncMock(
        return_value=SearchObservation(
            provider="brave",
            query="query",
            results=[
                SearchResult(title="Unsafe", url=unsafe),
                SearchResult(title="Source", url=URL),
            ],
        )
    )
    seeds, observations = await discover_seed_sources(
        "Goal",
        TaskSpec(),
        policy(),
        config(),
        build_research_plan({"type": "object"}, None),
        search,
        lambda _: [],
        canonical_url,
    )
    assert seeds == [URL]
    assert observations[0]["results"] == [{"title": "Source", "url": URL, "description": ""}]
    assert search.await_count == 1
