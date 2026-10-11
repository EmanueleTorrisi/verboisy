# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Malformed or mutable cache entries must not replace durable query acquisitions."""

import asyncio
import copy
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.initial_discovery import publish_initial_discovery
from verboisy.core.initial_query_journal import (
    initial_query_journal,
    journal_initial_query,
    replay_initial_query,
)
from verboisy.core.planner import build_research_plan
from verboisy.evidence.models import TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.product import SourcePolicy
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

OBSERVATION = {"results": [{"url": "https://example.test/", "metadata": {"labels": ["original"]}}]}
BAD_ENTRIES = [None, [], {}, {"payload": None}, {"payload": []}]
BAD_ENTRIES += [
    {"payload": value}
    for value in [
        {},
        {"query": None, "observation": OBSERVATION},
        {"query": 1, "observation": OBSERVATION},
        {"query": "", "observation": OBSERVATION},
        {"query": " ", "observation": OBSERVATION},
        {"query": "query"},
        {"query": "query", "observation": None},
        {"query": "query", "observation": []},
        {"query": "query", "observation": {}},
        {"query": "query", "observation": {"results": None}},
        {"query": "query", "observation": {"results": {}}},
        {"query": "query", "observation": {"results": []}},
        {"query": "query", "observation": {"results": [float("nan")]}},
    ]
]


@pytest.mark.parametrize("entry", BAD_ENTRIES)
def test_invalid_saved_entry_preserves_outer_context(entry):
    writer = MagicMock()
    with initial_query_journal(
        [{"payload": {"query": "outer", "observation": OBSERVATION}}], writer
    ):
        with (
            pytest.raises(VerboisyError, match="discovery result failed integrity"),
            initial_query_journal([entry], writer),
        ):
            pytest.fail("invalid cache was bound")
        assert replay_initial_query("outer") == OBSERVATION
        assert replay_initial_query("query") is None
    writer.assert_not_called()
    assert replay_initial_query("outer") is None


@pytest.mark.parametrize(
    "query,observation",
    [
        (None, OBSERVATION),
        (1, OBSERVATION),
        ("", OBSERVATION),
        (" ", OBSERVATION),
        ("query", None),
        ("query", []),
        ("query", {}),
        ("query", {"results": None}),
        ("query", {"results": {}}),
        ("query", {"results": [float("inf")]}),
    ],
)
def test_invalid_live_entry_never_calls_writer_or_publishes(query, observation):
    writer = MagicMock()
    with initial_query_journal([], writer):
        with pytest.raises(VerboisyError, match="discovery result failed integrity"):
            journal_initial_query(query, observation)
        assert replay_initial_query("query") is None
    writer.assert_not_called()


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize(
    "changed",
    [
        {"results": [{"url": "https://other.test/"}]},
        {**OBSERVATION, "provider": "different"},
        {**OBSERVATION, "reported_tokens": 1},
        {"results": [{"url": "https://example.test/", "metadata": {"labels": ["changed"]}}]},
    ],
)
def test_conflicting_query_acquisitions_never_replace_original(saved, changed):
    writer = MagicMock()
    original = {"payload": {"query": "query", "observation": OBSERVATION}}
    with initial_query_journal([original], writer):
        with pytest.raises(VerboisyError, match="query has conflicting results"):
            if saved:
                with initial_query_journal(
                    [original, {"payload": {"query": "query", "observation": changed}}], writer
                ):
                    pytest.fail("conflicting cache was bound")
            else:
                journal_initial_query("query", changed)
        assert replay_initial_query("query") == OBSERVATION
    writer.assert_not_called()


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("mutation", ["input", "nested_input", "output", "nested_output"])
def test_replay_copies_isolate_input_and_output_mutation(saved, mutation):
    value = copy.deepcopy(OBSERVATION)
    events = [{"payload": {"query": "query", "observation": value}}] if saved else []
    writer = MagicMock()
    with initial_query_journal(events, writer):
        if not saved:
            journal_initial_query("query", value)
        target = value if "input" in mutation else replay_initial_query("query")
        if mutation.startswith("nested"):
            target["results"][0]["metadata"]["labels"].append("changed")
        else:
            target["results"] = []
        assert replay_initial_query("query") == OBSERVATION
    assert replay_initial_query("query") is None


def test_mutating_writer_cannot_change_private_replay_or_caller_value():
    value = copy.deepcopy(OBSERVATION)

    def write(payload):
        payload["observation"]["results"][0]["metadata"]["labels"].append("writer changed")

    with initial_query_journal([], write):
        journal_initial_query("query", value)
        assert replay_initial_query("query") == OBSERVATION
        assert value == OBSERVATION


@pytest.mark.parametrize(
    "failure", [OSError, RuntimeError, KeyboardInterrupt, asyncio.CancelledError]
)
def test_failed_writer_keeps_query_retryable_and_restores_context(failure):
    writer = MagicMock(side_effect=failure("injected failure"))
    with initial_query_journal([], writer):
        with pytest.raises(failure):
            journal_initial_query("query", OBSERVATION)
        assert replay_initial_query("query") is None
        writer.side_effect = None
        journal_initial_query("query", OBSERVATION)
        assert replay_initial_query("query") == OBSERVATION
    assert writer.call_count == 2
    assert replay_initial_query("query") is None


@pytest.mark.parametrize("saved", [False, True])
def test_identical_repeated_entries_are_idempotent(saved):
    value = {"results": [{"metadata": {"labels": ["original"]}, "url": "https://example.test/"}]}
    original = {"payload": {"query": "query", "observation": OBSERVATION}}
    writer = MagicMock()
    with initial_query_journal(
        [original, {"payload": {"query": "query", "observation": value}}] if saved else [], writer
    ):
        journal_initial_query("query", OBSERVATION)
        journal_initial_query("query", value)
        assert replay_initial_query("query") == OBSERVATION
    assert writer.call_count == (0 if saved else 1)


def test_empty_fresh_search_is_not_cached_and_unbound_calls_remain_noops():
    writer = MagicMock()
    journal_initial_query("query", {})
    with initial_query_journal([], writer):
        journal_initial_query("query", {"results": []})
        assert replay_initial_query("query") is None
    writer.assert_not_called()


async def test_null_saved_observation_pauses_before_paid_discovery(tmp_path):
    with closing(ResearchStore(tmp_path / "resume.db")) as store:
        task = TaskSpec()
        rid = store.create("Goal", {"type": "object"}, task, None)
        store.finish(rid, "RUNNING", "fixture", 9, 17)
        store.event(rid, "initial_query_result", {"query": "Goal", "observation": None})
        before_events = store.events(rid)
        before_task = store.load(rid)["task_json"]
        discover = AsyncMock(side_effect=AssertionError("paid search repeated"))
        with pytest.raises(VerboisyError, match="discovery result failed integrity") as caught:
            await publish_initial_discovery(
                store,
                rid,
                task,
                SourcePolicy(),
                Settings(_env_file=None, search_provider="disabled"),
                build_research_plan({"type": "object"}, None),
                discover,
                LLMClient,
            )
        assert caught.value.details["run_id"] == rid
        assert discover.await_count == 0
        assert store.load(rid)["status"] == "PAUSED"
        assert store.load(rid)["task_json"] == before_task
        assert (store.load(rid)["tokens"], store.load(rid)["reserved"]) == (9, 17)
        assert store.events(rid) == before_events
        assert store.pages(rid) == []
