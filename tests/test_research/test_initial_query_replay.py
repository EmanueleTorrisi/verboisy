# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A later query failure must not charge again for an earlier completed query."""

import asyncio
import json

import pytest
from verboisy import arun
from verboisy.core.search import _openai_search_request
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import BudgetExceededError

from tests.test_research import test_initial_search_accounting as fixtures

fixture = fixtures.fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_resume_reuses_prior_query_after_later_budget_or_cancellation(fixture, cancelled):
    config, _, requests, replies = fixture
    first_query = f"site:alpha.test {fixtures.GOAL}"
    units = (
        len(json.dumps(_openai_search_request(first_query, config), ensure_ascii=False).encode())
        + config.max_tokens
    )
    config.model_request_budget = units * (4 if cancelled else 1)
    replies.append(fixtures.reply(url="https://alpha.test/first"))
    if cancelled:
        replies.append(asyncio.CancelledError())
    expected_error = asyncio.CancelledError if cancelled else BudgetExceededError
    with pytest.raises(expected_error):
        await arun(
            goal=fixtures.GOAL,
            schema="[name,website]",
            include=["alpha.test", "bravo.test"],
            onlyinclude=True,
            config=config,
        )
    before, journal, _ = fixtures.inspect(config)
    assert before["status"] == "PAUSED"
    assert len(requests) == (2 if cancelled else 1)
    config.model_request_budget = units * 4
    replies.append(fixtures.reply(url="https://bravo.test/second"))
    result = await arun(resume=before["id"], config=config, max_steps=1)
    after, after_journal, task = fixtures.inspect(config)
    assert result.run_id == before["id"]
    assert len(requests) == (3 if cancelled else 2)
    query_counts = [json.loads(request.content)["input"] for request in requests]
    assert query_counts.count(_openai_search_request(first_query, config)["input"]) == 1
    assert task.seed_urls == ["https://alpha.test/first", "https://bravo.test/second"]
    assert after["tokens"] == 34
    assert after["reserved"] == units * len(requests)
    assert after_journal[: len(journal)] == journal
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(result.run_id, "initial_query_result")) == 2
        assert len(store.events(result.run_id, "source_discovery")) == 2
    finally:
        store.close()


def test_failed_query_journal_does_not_publish_replay_state():
    from unittest.mock import MagicMock

    from verboisy.core.initial_query_journal import (
        initial_query_journal,
        journal_initial_query,
        replay_initial_query,
    )

    observation = {"results": [{"url": "https://alpha.test/first"}]}
    write = MagicMock(side_effect=OSError("Query journal failed"))
    with initial_query_journal([], write):
        with pytest.raises(OSError, match="Query journal failed"):
            journal_initial_query("query", observation)
        assert replay_initial_query("query") is None
    assert replay_initial_query("query") is None


@pytest.mark.asyncio
async def test_concurrent_query_journals_do_not_share_run_results():
    from unittest.mock import MagicMock

    from verboisy.core.initial_query_journal import initial_query_journal, replay_initial_query

    ready = [asyncio.Event(), asyncio.Event()]

    async def bound(index):
        observation = {"results": [{"url": f"https://run{index}.test/"}]}
        events = [{"payload": {"query": "shared query", "observation": observation}}]
        with initial_query_journal(events, MagicMock()):
            ready[index].set()
            await ready[1 - index].wait()
            assert replay_initial_query("shared query") == observation
        assert replay_initial_query("shared query") is None

    await asyncio.gather(bound(0), bound(1))
    assert replay_initial_query("shared query") is None
