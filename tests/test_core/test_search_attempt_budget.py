# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Separate provider-attempt limits survive interruption and run resume."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.core.search import brave_search, openai_search, search_accounting, web_search
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchBudgetExceededError, SearchUnavailableError

from tests.test_core.test_brave_search_accounting import response, settings
from tests.test_core.test_brave_search_accounting import transport as _transport

transport = _transport


@pytest.mark.parametrize("provider", ["openai", "brave"])
@pytest.mark.parametrize("bound", [False, True])
async def test_zero_prevents_dns_and_transport(tmp_path, monkeypatch, provider, bound):
    config = settings(tmp_path)
    config.search_request_budget = 0
    dns = AsyncMock(side_effect=AssertionError("Unexpected DNS"))
    monkeypatch.setattr("verboisy.core.search.validate_url", dns)
    events = []
    client = LLMClient(config=config)
    search = openai_search if provider == "openai" else brave_search
    if bound:
        with search_accounting(client, events.append), pytest.raises(SearchBudgetExceededError):
            await search("Find universities", config)
        assert events[-1]["status"] == "blocked"
    else:
        with pytest.raises(SearchBudgetExceededError):
            await search("Find universities", config)
        assert events == []
    assert client.search_requests == client.reserved_tokens == 0
    dns.assert_not_awaited()


@pytest.mark.parametrize("failure", [None, response(503), asyncio.CancelledError()])
async def test_attempt_is_consumed_even_on_failure(tmp_path, transport, failure):
    config = settings(tmp_path)
    config.search_request_budget = 1
    requests = transport(response() if failure is None else failure)
    client = LLMClient(config=config)
    events = []
    with search_accounting(client, events.append):
        if failure is None:
            await brave_search("Find universities", config)
        else:
            kind = (
                asyncio.CancelledError
                if isinstance(failure, asyncio.CancelledError)
                else SearchUnavailableError
            )
            with pytest.raises(kind):
                await brave_search("Find universities", config)
        with pytest.raises(SearchBudgetExceededError):
            await brave_search("Retry", config)
    assert len(requests) == client.search_requests == 1
    assert events[-1]["status"] == "blocked"
    assert client.reserved_tokens == client.total_tokens == 0


async def test_fallback_is_a_separate_attempt(tmp_path, transport):
    config = settings(tmp_path)
    config.search_provider = "auto"
    config.search_request_budget = 1
    requests = transport(response(), httpx.Response(503, json={}))
    client = LLMClient(config=config)
    events = []
    with search_accounting(client, events.append), pytest.raises(SearchBudgetExceededError):
        await web_search("Find universities", config)
    assert len(requests) == 1
    assert requests[0].url.host == "api.openai.com"
    assert [(e["provider"], e["status"]) for e in events] == [
        ("openai", "reserved"),
        ("openai", "failed"),
        ("brave", "blocked"),
    ]
    assert client.search_requests == 1


async def test_initial_resume_keeps_spent_attempts(tmp_path, transport, monkeypatch):
    config = settings(tmp_path)
    config.search_request_budget = 1
    requests = transport(response(503))
    with pytest.raises(SearchUnavailableError):
        await arun(goal="Find universities", schema="[name]", config=config)
    with pytest.raises(SearchBudgetExceededError):
        await arun(resume=True, config=config)
    assert len(requests) == 1
    store = ResearchStore(config.sqlite_db_path)
    try:
        state = store.load(None)
        rid = state["id"]
        assert state["reason"] == "search_request_budget"
        assert store.search_attempt_count(rid) == 1
        runner = ResearchRunner(store, rid, config)
        assert runner.client.search_requests == 1
    finally:
        store.close()
    config.search_request_budget = 2
    transport(response())

    async def stop(runner, steps):
        runner.store.finish(
            runner.rid,
            "PAUSED",
            "fixture",
            runner.client.total_tokens,
            runner.client.reserved_tokens,
        )
        return "PAUSED", "fixture"

    monkeypatch.setattr(ResearchRunner, "run", stop)
    result = await arun(resume=rid, config=config, max_steps=1)
    assert result.run_id == rid
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.search_attempt_count(rid) == 2
    finally:
        store.close()


async def test_runner_reports_search_budget_stop(tmp_path, monkeypatch):
    from tests.test_storage.test_unit_replay_integrity import ledger

    config = settings(tmp_path)
    with ledger(tmp_path) as (store, rid, _):
        runner = ResearchRunner(store, rid, config)
        runner.browser.start = AsyncMock(side_effect=SearchBudgetExceededError("Fixture limit"))
        runner.browser.close = AsyncMock()
        assert await runner.run(1) == ("PAUSED", "search_request_budget")
        assert store.load(rid)["reason"] == "search_request_budget"


@pytest.mark.parametrize("limit", [None, 0, 1, 20])
def test_budget_settings_supported(limit):
    assert Settings(_env_file=None, search_request_budget=limit).search_request_budget == limit


def test_negative_budget_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, search_request_budget=-1)


def test_environment_budget(monkeypatch):
    monkeypatch.setenv("SEARCH_REQUEST_BUDGET", "0")
    assert Settings(_env_file=None).search_request_budget == 0


def test_count_unique_reservations_and_ignore_blocked_or_malformed(tmp_path):
    from verboisy.evidence.models import TaskSpec

    store = ResearchStore(settings(tmp_path).sqlite_db_path)
    try:
        rid = store.create("Fixture", {"type": "object"}, TaskSpec(), None)
        for payload in [
            {"status": "reserved", "attempt_id": "a"},
            {"status": "reserved", "attempt_id": "a"},
            {"status": "blocked", "attempt_id": "b"},
            {"status": "reserved", "attempt_id": None},
        ]:
            store.event(rid, "search_request", payload)
        assert store.search_attempt_count(rid) == 1
        assert json.loads(store.load(rid)["task_json"])
    finally:
        store.close()
