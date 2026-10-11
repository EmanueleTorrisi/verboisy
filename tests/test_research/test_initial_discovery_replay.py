# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Interrupted seed publication reuses durable results without repeating paid search."""

import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.core.planner import ResearchPlan
from verboisy.storage.research import ResearchStore

from tests.test_research import test_initial_search_accounting as fixtures

fixture = fixtures.fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["task", "observation", "queue", "defer", "frontier"])
async def test_resume_replays_successful_search_after_publication_failure(fixture, stage):
    config, _, requests, replies = fixture
    urls = ["https://example.test/first", "https://example.test/second"]
    response = fixtures.reply()
    value = response.json()
    value["output"][0]["action"]["sources"] = [{"url": url} for url in urls]
    import httpx

    replies.append(httpx.Response(200, json=value))
    original_event = ResearchStore.event

    def event(self, rid, kind, payload):
        if kind == {"observation": "source_discovery", "frontier": "seed_frontier"}.get(stage):
            raise OSError("Publication interrupted")
        return original_event(self, rid, kind, payload)

    method = {"task": "update_task", "queue": "queue", "defer": "defer"}.get(stage)
    with patch.object(ResearchPlan, "split_initial_sources", return_value=(urls[:1], urls[1:])):
        with ExitStack() as stack:
            stack.enter_context(patch.object(ResearchStore, "event", event))
            if method:
                stack.enter_context(
                    patch.object(
                        ResearchStore, method, side_effect=OSError("Publication interrupted")
                    )
                )
            with pytest.raises(OSError, match="Publication interrupted"):
                await arun(
                    goal=fixtures.GOAL,
                    schema="[name,website]",
                    include=["example.test"],
                    onlyinclude=True,
                    config=config,
                )
        before, journal, _ = fixtures.inspect(config)
        assert before["status"] == "PAUSED"
        assert len(requests) == 1
        result = await arun(resume=before["id"], config=config, max_steps=1)
    after, after_journal, task = fixtures.inspect(config)
    assert result.run_id == before["id"]
    assert len(requests) == 1
    assert after_journal == journal
    assert (after["tokens"], after["reserved"]) == (before["tokens"], before["reserved"])
    assert task.seed_urls == urls
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id)["pages"] == {"queued": 1, "deferred": 1}
        assert len(store.events(result.run_id, "source_discovery")) == 1
        assert len(store.events(result.run_id, "seed_frontier")) == 1
        assert len(store.events(result.run_id, "initial_discovery_result")) == 1
        assert json.loads(store.load(result.run_id)["task_json"])["seed_urls"] == urls
    finally:
        store.close()
