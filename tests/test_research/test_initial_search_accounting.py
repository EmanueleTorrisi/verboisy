# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Initial discovery reserves against a durable run before provider transport."""

import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.core.search import _openai_search_request
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError, SearchUnavailableError, VerboisyError

GOAL = "Find universities in Italy"


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        search_provider="openai",
        openai_api_key="offline-key",
        max_tokens=64,
    )
    body = _openai_search_request(GOAL, config)
    units = len(json.dumps(body, ensure_ascii=False).encode()) + config.max_tokens
    requests = []
    replies = []
    original = httpx.AsyncClient

    def handle(request):
        with sqlite3.connect(config.sqlite_db_path) as db:
            state = db.execute(
                "SELECT id,reserved FROM research_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            assert state[1] >= units
            event = db.execute(
                "SELECT payload FROM events WHERE run_id=? AND kind='search_request' "
                "ORDER BY id DESC LIMIT 1",
                (state[0],),
            ).fetchone()
            assert json.loads(event[0])["status"] == "reserved"
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr("verboisy.core.search.validate_url", AsyncMock())
    monkeypatch.setattr(
        "verboisy.core.search.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
    )
    monkeypatch.setattr(
        "verboisy.browser.context.BrowserManager.start",
        AsyncMock(side_effect=AssertionError("Unexpected browser")),
    )
    monkeypatch.setattr(
        "verboisy.llm.client._complete", AsyncMock(side_effect=AssertionError("Unexpected model"))
    )

    async def stop(runner, steps):
        runner.store.finish(
            runner.rid,
            "PAUSED",
            "offline_fixture",
            runner.client.total_tokens,
            runner.client.reserved_tokens,
        )
        return "PAUSED", "offline_fixture"

    monkeypatch.setattr(ResearchRunner, "run", stop)
    return config, units, requests, replies


def reply(tokens=17, status=200, url="https://example.test/universities"):
    return httpx.Response(
        status,
        json={
            "usage": {"total_tokens": tokens},
            "output": [{"type": "web_search_call", "action": {"sources": [{"url": url}]}}],
        },
    )


def inspect(config):
    store = ResearchStore(config.sqlite_db_path)
    try:
        state = store.load(None)
        events = store.events(state["id"], "search_request")
        task = TaskSpec.model_validate_json(state["task_json"])
        return state, events, task
    finally:
        store.close()


async def test_success_is_durable_and_resume_does_not_repeat_discovery(fixture):
    config, units, requests, replies = fixture
    replies.append(reply())
    result = await arun(goal=GOAL, schema="[name,website]", config=config, max_steps=1)
    state, events, task = inspect(config)
    assert state["id"] == result.run_id
    assert (state["reserved"], state["tokens"]) == (units, 17)
    assert [e["payload"]["status"] for e in events] == ["reserved", "succeeded"]
    assert task.seed_urls == ["https://example.test/universities"]
    resumed = await arun(resume=result.run_id, config=config, max_steps=1)
    assert resumed.run_id == result.run_id
    assert len(requests) == 1
    assert inspect(config) == (state, events, task)


async def test_budget_failure_leaves_resumable_run(fixture):
    config, units, requests, replies = fixture
    config.model_request_budget = 1
    with pytest.raises(BudgetExceededError) as error:
        await arun(goal=GOAL, schema="[name,website]", config=config)
    state, events, _ = inspect(config)
    assert state["status"] == "PAUSED"
    assert state["reason"] == "model_request_budget"
    assert error.value.details["run_id"] == state["id"]
    assert (state["reserved"], state["tokens"]) == (0, 0)
    assert events == []  # The individual payload guard blocks before reservation.
    assert requests == []
    config.model_request_budget = units
    replies.append(reply())
    result = await arun(resume=True, config=config, max_steps=1)
    assert result.run_id == state["id"]
    assert inspect(config)[0]["reserved"] == units


@pytest.mark.parametrize("failure", [reply(status=503), asyncio.CancelledError()])
async def test_failed_attempt_retained_and_retry_uses_same_run(fixture, failure):
    config, units, requests, replies = fixture
    replies.append(failure)
    kind = asyncio.CancelledError if isinstance(failure, BaseException) else SearchUnavailableError
    with pytest.raises(kind):
        await arun(goal=GOAL, schema="[name,website]", config=config)
    state, events, _ = inspect(config)
    assert state["status"] == "PAUSED"
    assert state["reserved"] == units
    assert events[-1]["payload"]["status"] in ("failed", "cancelled")
    replies.append(reply())
    resumed = await arun(resume=True, config=config, max_steps=1)
    assert resumed.run_id == state["id"]
    after, events, _ = inspect(config)
    assert (after["reserved"], after["tokens"]) == (2 * units, 17)
    assert len(requests) == 2
    assert len({e["payload"]["attempt_id"] for e in events}) == 2


async def test_no_permitted_sources_leaves_recoverable_run(fixture):
    config, units, requests, replies = fixture
    replies.append(reply(url="https://blocked.test/data"))
    with pytest.raises(VerboisyError, match="no permitted"):
        await arun(goal=GOAL, schema="[name,website]", avoid=["blocked.test"], config=config)
    state, _, _ = inspect(config)
    assert state["status"] == "PAUSED"
    assert state["reserved"] == units
    replies.append(reply())
    resumed = await arun(resume=True, config=config, max_steps=1)
    assert resumed.run_id == state["id"]


async def test_schema_target_conflict_precedes_search(fixture):
    config, _, requests, _ = fixture
    with pytest.raises(VerboisyError, match="collection limits"):
        await arun(
            goal=GOAL,
            schema={
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"type": "string"}}},
                "maxItems": 1,
            },
            maxrows=2,
            config=config,
        )
    assert requests == []


async def test_initial_search_exhaustion_blocks_extraction(fixture, monkeypatch):
    config, units, requests, replies = fixture
    config.model_request_budget = units
    replies.append(reply())

    async def extract(runner, steps):
        await runner.client.complete_json("Return JSON", "Extract records")

    monkeypatch.setattr(ResearchRunner, "run", extract)
    with pytest.raises(BudgetExceededError):
        await arun(goal=GOAL, schema="[name,website]", config=config)
    state, _, _ = inspect(config)
    assert state["reserved"] == units
    assert state["tokens"] == 17
    assert len(requests) == 1


async def test_resume_retry_cannot_reset_spent_budget(fixture):
    config, units, requests, replies = fixture
    config.model_request_budget = units
    replies.append(reply(status=503))
    with pytest.raises(SearchUnavailableError):
        await arun(goal=GOAL, schema="[name,website]", config=config)
    with pytest.raises(BudgetExceededError):
        await arun(resume=True, config=config)
    state, events, _ = inspect(config)
    assert state["reserved"] == units
    assert state["reason"] == "model_request_budget"
    assert len(requests) == 1
    assert events[-1]["payload"]["status"] == "blocked"


async def test_unexpected_failure_pauses_without_replacing_exception(fixture):
    config, units, _, replies = fixture
    failure = RuntimeError("fixture failure")
    replies.append(failure)
    with pytest.raises(RuntimeError) as error:
        await arun(goal=GOAL, schema="[name,website]", config=config)
    assert error.value is failure
    state, _, _ = inspect(config)
    assert state["status"] == "PAUSED"
    assert state["reserved"] == units


async def test_resume_restores_source_policy(fixture):
    config, _, requests, replies = fixture
    replies.append(reply(status=503))
    with pytest.raises(SearchUnavailableError):
        await arun(
            goal=GOAL,
            schema="[name,website]",
            include=["example.test"],
            onlyinclude=True,
            config=config,
        )
    replies.append(reply())
    result = await arun(resume=True, config=config, max_steps=1)
    bodies = [json.loads(request.content) for request in requests]
    assert all("site:example.test" in body["input"] for body in bodies)
    assert result.run_id == inspect(config)[0]["id"]
