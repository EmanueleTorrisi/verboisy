# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Brave attempts are journaled without fabricating model token usage."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.core.search import brave_search, search_accounting, web_search
from verboisy.evidence.models import TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError


def settings(tmp_path):
    return Settings(
        _env_file=None,
        search_provider="brave",
        brave_search_api_key="offline-brave-key",
        openai_api_key="offline-openai-key",
        max_tokens=64,
        sqlite_db_path=str(tmp_path / "run.db"),
    )


def response(status=200):
    return httpx.Response(
        status,
        json={
            "type": "search",
            "web": {"results": [{"title": "Fixture", "url": "https://example.test/data"}]},
        },
    )


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    monkeypatch.setattr("verboisy.core.search.validate_url", AsyncMock())

    def install(brave_reply, openai_reply=None):
        def handle(request):
            requests.append(request)
            value = brave_reply if request.url.host == "api.search.brave.com" else openai_reply
            if isinstance(value, BaseException):
                raise value
            return value

        monkeypatch.setattr(
            "verboisy.core.search.httpx.AsyncClient",
            lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
        )
        return requests

    return install


@pytest.mark.parametrize(
    "failure", [None, response(503), asyncio.CancelledError(), RuntimeError("fixture")]
)
async def test_brave_attempt_states_and_no_model_units(tmp_path, transport, failure):
    config = settings(tmp_path)
    client = LLMClient(config=config)
    events = []
    requests = transport(response() if failure is None else failure)
    expected = (
        "succeeded"
        if failure is None
        else "cancelled"
        if isinstance(failure, asyncio.CancelledError)
        else "failed"
    )
    with search_accounting(client, events.append):
        if failure is None:
            result = await brave_search("Find universities", config)
            assert result.results[0].url == "https://example.test/data"
            assert result.reported_tokens is None
        else:
            kind = type(failure) if isinstance(failure, BaseException) else SearchUnavailableError
            with pytest.raises(kind):
                await brave_search("Find universities", config)
    assert [event["status"] for event in events] == ["reserved", expected]
    assert len({event["attempt_id"] for event in events}) == 1
    assert all(
        event["request_units"] is None
        and event["reported_tokens"] is None
        and event["provider_request_count"] == 1
        for event in events
    )
    assert client.total_tokens == client.reserved_tokens == 0
    assert len(requests) == 1
    assert "offline-brave-key" not in json.dumps(events)
    if failure is None:
        await brave_search("Standalone request", config)
    assert len(events) == 2


@pytest.mark.parametrize("invalid", ["missing", "blank", "long", "words"])
async def test_invalid_inputs_do_not_reserve(tmp_path, transport, invalid):
    config = settings(tmp_path)
    query = "Find universities"
    if invalid == "missing":
        config.brave_search_api_key = None
    if invalid == "blank":
        config.brave_search_api_key = SecretStr(" ")
    if invalid == "long":
        query = "x" * 601
    if invalid == "words":
        query = "x " * 76
    requests = transport(response())
    events = []
    with (
        search_accounting(LLMClient(config=config), events.append),
        pytest.raises(SearchUnavailableError),
    ):
        await brave_search(query, config)
    assert requests == events == []


async def test_auto_fallback_journals_each_provider_separately(tmp_path, transport):
    config = settings(tmp_path)
    config.search_provider = "auto"
    client = LLMClient(config=config)
    events = []
    requests = transport(response(), httpx.Response(503, json={}))
    with search_accounting(client, events.append):
        result = await web_search("Find universities", config)
    assert result.provider == "brave"
    assert [(e["provider"], e["status"]) for e in events] == [
        ("openai", "reserved"),
        ("openai", "failed"),
        ("brave", "reserved"),
        ("brave", "succeeded"),
    ]
    assert len(requests) == 2
    assert client.reserved_tokens == events[0]["request_units"]
    assert client.total_tokens == 0


async def test_brave_initial_discovery_is_durable_and_portable(tmp_path, transport, monkeypatch):
    config = settings(tmp_path)
    requests = transport(response())

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
    result = await arun(
        goal="Find universities", schema="[name]", config=config, export=tmp_path / "rows.json"
    )
    await arun(resume=result.run_id, config=config)
    assert len(requests) == 1
    store = ResearchStore(config.sqlite_db_path)
    try:
        state = store.load(result.run_id)
        assert state["tokens"] == state["reserved"] == 0
        events = store.events(result.run_id, "search_request")
        assert [e["payload"]["status"] for e in events] == ["reserved", "succeeded"]
    finally:
        store.close()
    manifest = json.loads((tmp_path / "rows.json.manifest.json").read_text())
    assert manifest["search_attempts_reserved"] == {"openai": 0, "brave": 1}
    portable = json.loads((tmp_path / "rows.json.events.json").read_text())
    assert [e for e in portable["events"] if e["kind"] == "search_request"] == events


def test_manifest_counts_unique_reserved_attempts_and_protects_metadata(tmp_path):
    config = settings(tmp_path)
    store = ResearchStore(config.sqlite_db_path)
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    task = TaskSpec()
    try:
        rid = store.create("Fixture", schema, task, None)
        for payload in [
            {"provider": "brave", "status": "reserved", "attempt_id": "b"},
            {"provider": "brave", "status": "reserved", "attempt_id": "b"},
            {"provider": "brave", "status": "failed", "attempt_id": "b"},
            {"provider": "openai", "status": "reserved", "attempt_id": "a"},
            {"provider": "openai", "status": "blocked", "attempt_id": "c"},
            {"provider": "brave", "status": "reserved", "attempt_id": None},
            {"provider": "other", "status": "reserved", "attempt_id": "d"},
        ]:
            store.event(rid, "search_request", payload)
        path = export_dataset(
            store,
            rid,
            tmp_path / "rows.json",
            schema,
            task,
            metadata={
                "search_attempts_reserved": {"brave": 999},
                "search_attempt_definition": "False claim",
            },
        )
        manifest = json.loads(path.read_text())
        assert manifest["search_attempts_reserved"] == {"openai": 1, "brave": 1}
        assert "not confirmed billable" in manifest["search_attempt_definition"]
    finally:
        store.close()


async def test_repair_search_journal_survives_resume(tmp_path, transport):
    from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger

    config = settings(tmp_path)
    transport(response())
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "mystery units")
        runner = ResearchRunner(store, rid, config)
        assert await runner.discover_dataset_repair_source(runner.dataset_consistency_repairs())
        events = store.events(rid, "search_request")
        assert [e["payload"]["status"] for e in events] == ["reserved", "succeeded"]
        restored = ResearchRunner(store, rid, config)
        assert restored.client.total_tokens == restored.client.reserved_tokens == 0
        assert store.events(rid, "search_request") == events


async def test_concurrent_brave_contexts_are_isolated(tmp_path, transport):
    config = settings(tmp_path)
    transport(response())
    journals = [[], []]

    async def invoke(index):
        with search_accounting(LLMClient(config=config), journals[index].append):
            await brave_search(f"Query {index}", config)

    await asyncio.gather(invoke(0), invoke(1))
    assert all(len(events) == 2 for events in journals)
    assert all(
        event["query"] == f"Query {index}"
        for index, events in enumerate(journals)
        for event in events
    )
    assert journals[0][0]["attempt_id"] != journals[1][0]["attempt_id"]
