# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Repair search shares and durably reserves the runner's model request budget."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.search import _openai_search_request, openai_search, search_accounting
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger

QUERY = "Alba population unit measurement scale"


def settings(tmp_path):
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "replay.db"),
        search_provider="openai",
        openai_api_key="offline-fixture-key",
        max_tokens=64,
        llm_retries=0,
    )
    payload = _openai_search_request(QUERY, config)
    units = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + config.max_tokens
    config.model_request_budget = units
    return config, units


def response(usage=None, status=200):
    body = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"sources": [{"url": "https://example.test/repair"}]},
            }
        ]
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    monkeypatch.setattr("verboisy.core.search.validate_url", AsyncMock())

    def install(reply):
        def handle(request):
            requests.append(request)
            return reply

        monkeypatch.setattr(
            "verboisy.core.search.httpx.AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
        )
        return requests

    return install


async def test_runner_search_blocks_extraction_and_survives_resume(tmp_path, transport):
    config, units = settings(tmp_path)
    requests = transport(response({"total_tokens": 17}))
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "mystery units")
        evidence = store.evidence(rid)
        runner = ResearchRunner(store, rid, config)
        assert await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
        extraction = AsyncMock(side_effect=AssertionError("Unexpected extraction"))
        with patch("verboisy.llm.client._complete", extraction), pytest.raises(BudgetExceededError):
            await runner.client.complete_json("Return JSON.", "Reply.")
        extraction.assert_not_awaited()
        assert len(requests) == 1
        assert store.load(rid)["reserved"] == units
        assert store.load(rid)["tokens"] == 17
        events = [event["payload"] for event in store.events(rid, "search_request")]
        assert [event["status"] for event in events] == ["reserved", "succeeded"]
        assert events[0]["attempt_id"] == events[1]["attempt_id"]
        assert events[0]["reported_tokens"] is None
        assert events[1]["reported_tokens"] == 17
        assert store.evidence(rid) == evidence
    reopened = ResearchStore(config.sqlite_db_path)
    try:
        resumed = ResearchRunner(reopened, rid, config)
        assert resumed.client.reserved_tokens == units
        assert resumed.client.total_tokens == 17
        with pytest.raises(BudgetExceededError):
            await resumed.client.complete_json("Return JSON.", "Reply.")
    finally:
        reopened.close()


async def test_cumulative_search_budget_rejection_is_journalled(tmp_path, transport):
    config, units = settings(tmp_path)
    requests = transport(response())
    client = LLMClient(config=config)
    client.reserve_request(1)
    events = []
    with search_accounting(client, events.append), pytest.raises(BudgetExceededError):
        await openai_search(QUERY, config)
    assert requests == []
    assert client.reserved_tokens == 1
    assert [event["status"] for event in events] == ["blocked"]
    assert events[0]["request_units"] == units


async def test_failed_attempts_retain_durable_reservations(tmp_path, transport):
    config, units = settings(tmp_path)
    config.model_request_budget = units * 2
    requests = transport(response(status=503))
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "mystery units")
        for attempt in range(2):
            runner = ResearchRunner(store, rid, config)
            assert not await runner.discover_dataset_repair_source(
                runner.dataset_consistency_repairs()
            )
            assert store.load(rid)["reserved"] == units * (attempt + 1)
        assert len(requests) == 2
        events = [event["payload"] for event in store.events(rid, "search_request")]
        assert [event["status"] for event in events] == ["reserved", "failed", "reserved", "failed"]
        assert events[0]["attempt_id"] != events[2]["attempt_id"]
        assert all(event["reported_tokens"] is None for event in events)


async def test_cancelled_search_retains_reservation_and_resets_context(tmp_path, transport):
    config, units = settings(tmp_path)
    client = LLMClient(config=config)
    events = []
    with (
        search_accounting(client, events.append),
        patch(
            "verboisy.core.search._openai_search_transport",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await openai_search(QUERY, config)
    assert client.reserved_tokens == units
    assert [event["status"] for event in events] == ["reserved", "cancelled"]
    requests = transport(response({"total_tokens": 17}))
    assert (await openai_search(QUERY, config)).reported_tokens == 17
    assert len(requests) == 1
    assert client.reserved_tokens == units
    assert client.total_tokens == 0


@pytest.mark.parametrize(
    "usage,expected",
    [
        (None, None),
        ({}, None),
        ({"total_tokens": True}, None),
        ({"total_tokens": -1}, None),
        ({"total_tokens": 1.5}, None),
        ({"total_tokens": "17"}, None),
        ([], None),
        ({"total_tokens": 0}, 0),
        ({"total_tokens": 17}, 17),
    ],
)
async def test_usage_is_known_only_for_nonnegative_integer(tmp_path, transport, usage, expected):
    config, units = settings(tmp_path)
    transport(response(usage))
    client = LLMClient(config=config)
    events = []
    with search_accounting(client, events.append):
        observation = await openai_search(QUERY, config)
    assert observation.reported_tokens == expected
    assert events[-1]["reported_tokens"] == expected
    assert client.total_tokens == (expected or 0)
    assert client.reserved_tokens == units


async def test_parallel_accounting_contexts_are_isolated(tmp_path, transport):
    config, units = settings(tmp_path)
    transport(response({"total_tokens": 17}))
    clients = [LLMClient(config=config), LLMClient(config=config)]
    journals = [[], []]

    async def search(index):
        with search_accounting(clients[index], journals[index].append):
            await asyncio.sleep(0)
            await openai_search(QUERY, config)

    await asyncio.gather(search(0), search(1))
    assert [client.reserved_tokens for client in clients] == [units, units]
    assert [client.total_tokens for client in clients] == [17, 17]
    assert all(
        [event["status"] for event in journal] == ["reserved", "succeeded"] for journal in journals
    )
