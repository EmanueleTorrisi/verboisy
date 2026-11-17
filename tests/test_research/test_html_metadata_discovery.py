# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay discovery through the real provider transport, task, evidence and CLI."""

import csv
import json
from contextlib import closing
from importlib import import_module
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner
from verboisy import arun
from verboisy.core import research
from verboisy.core.metadata_discovery import MetadataSourceScope
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.research_contract import validate_research_contract
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError, VerboisyError

HOST = "publications.example.test"
ORIGIN = f"https://{HOST}"
FIRST = f"{ORIGIN}/releases/2021/atlas/"
SECOND = f"{ORIGIN}/releases/2025/boreal/"
GOAL = "Find the Atlas and Boreal releases"
QUERY = f"site:{HOST} {GOAL}"
EXPECTED = [
    {"title": "Atlas \u2013 release notes", "published": "05-Jul-2021"},
    {"title": "Boreal \u2013 release notes", "published": "29 May 2025"},
]
SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "published": {"type": "string"}},
    "required": ["title", "published"],
    "additionalProperties": False,
}


def task(**changes):
    return TaskSpec.model_validate(
        {
            "allowed_hosts": [HOST],
            "include_paths": ["/releases/*/atlas/", "/releases/*/boreal/"],
            "exclude_paths": ["/releases/archive/*"],
            "target_records": 2,
            "max_pages": 2,
            "settle_ms": 0,
            "identity_fields": ["/title"],
            "csv_mode": "spreadsheet",
            "html_metadata": {
                "region": "main#release",
                "fields": {
                    "title": {"selector": "h1"},
                    "published": {"selector": "dl", "label": "Published"},
                },
            },
            "html_metadata_discovery": True,
            **changes,
        }
    )


def openai_reply(urls, *, actions=1, billed=1, tokens=50):
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "tool_usage": {"web_search": {"num_requests": billed}},
            "usage": {"total_tokens": tokens},
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "sources": [{"url": url} for url in urls] if index == 0 else [],
                    },
                }
                for index in range(actions)
            ],
        },
    )


@pytest.fixture
def replay(tmp_path, monkeypatch):
    docs = {
        url: (
            f'<main id="release"><h1>{row["title"]}</h1>'
            f"<dl><dt>Published</dt><dd>{row['published']}</dd></dl></main>"
        )
        for url, row in zip((FIRST, SECOND), EXPECTED, strict=True)
    }
    replies, requests, visited = [], [], []
    redirects = {}

    class Browser:
        def __init__(self, **_kwargs):
            self.navigation_scope = None

        async def start(self):
            return self

        async def navigate_to(self, url):
            assert self.navigation_scope(url)
            visited.append(url)
            self.url = url

        async def get_page(self):
            return self

        async def evaluate(self, _script, _limit):
            url = redirects.get(self.url, self.url)
            return {"url": url, "html": docs[url], "visible_html": docs[url], "oversized": False}

        async def close(self):
            pass

    original_client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return replies.pop(0)

    monkeypatch.setattr(research, "BrowserManager", Browser)
    monkeypatch.setattr("verboisy.core.search.validate_url", AsyncMock())
    monkeypatch.setattr(
        "verboisy.core.search.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        AsyncMock(side_effect=AssertionError("Literal extraction must not use a chat model")),
    )
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        search_provider="openai",
        openai_api_key="fixture-only",
        search_request_budget=1,
        openai_search_max_tool_calls=2,
        action_delay_seconds=0,
    )
    return config, replies, requests, visited, redirects


@pytest.mark.parametrize("provider", ["openai", "brave"])
def test_short_cli_goal_discovers_scoped_literal_sources(tmp_path, monkeypatch, replay, provider):
    config, replies, requests, visited, _ = replay
    urls = [
        SECOND,
        "https://unapproved.example.test/releases/2021/atlas/",
        f"https://other.{HOST}/releases/2021/atlas/",
        f"{ORIGIN}/releases/archive/atlas/",
        f"{ORIGIN}/releases/%2e%2e/atlas/",
        f"{FIRST}?different=1",
        FIRST,
        f"{FIRST}#notes",
    ]
    if provider == "openai":
        replies.append(openai_reply(urls))
    else:
        config.search_provider = "brave"
        config.brave_search_api_key = SecretStr("fixture-only")
        replies.append(
            httpx.Response(
                200,
                json={
                    "type": "search",
                    "web": {"results": [{"title": "A source", "url": u} for u in urls]},
                },
            )
        )
    cli = import_module("verboisy.cli.main")
    monkeypatch.setattr(cli, "Settings", lambda: config)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.json").write_text(task().model_dump_json(), encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            "--goal",
            GOAL,
            "--schema",
            "schema.json",
            "--task",
            "task.json",
            "--orderby",
            "title",
            "--date-format",
            "source",
            "--proof",
            "--no-animation",
            "--export",
            "rows.csv",
            "--export",
            "rows.json",
            "--max-steps",
            "2",
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert "Status: COMPLETED" in result.output
    (request,) = requests
    if provider == "openai":
        sent = json.loads(request.content)
        assert sent["input"].endswith(f"Research goal: {QUERY}")
        assert "one authoritative detail page per requested entity" in sent["input"]
        assert sent["max_tool_calls"] == 2
    else:
        assert request.url.params["q"] == QUERY
    assert visited == [FIRST, SECOND]
    expected = [{"id": index, **row} for index, row in enumerate(EXPECTED, 1)]
    assert json.loads((tmp_path / "rows.json").read_bytes()) == expected
    with (tmp_path / "rows.csv").open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == [{**row, "id": str(row["id"])} for row in expected]
    proof = (tmp_path / "rows.proof.txt").read_text(encoding="utf-8")
    assert proof.count("  /published:") == proof.count("  /title:") == 2
    manifests = [
        json.loads((tmp_path / f"rows.{extension}.manifest.json").read_bytes())
        for extension in ("csv", "json")
    ]
    assert manifests[0]["run_id"] == manifests[1]["run_id"]
    assert all(
        item["provenance"] == "literal_html_metadata"
        and item["search_attempts_reserved"][provider] == 1
        and item["records"] == 2
        for item in manifests
    )
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        state = store.load(manifests[0]["run_id"])
        saved = TaskSpec.model_validate_json(state["task_json"])
        assert saved.seed_urls == [FIRST, SECOND]
        assert state["goal"] == GOAL
        events = store.events(state["id"], "source_discovery")
        assert {item["url"] for item in events[0]["payload"]["results"]} == {FIRST, SECOND}
        entries = store.evidence(state["id"])
        assert len(entries) == 2
        for entry in entries:
            row = Candidate.model_validate(entry["candidate"])
            page = Snapshot.model_validate(entry["snapshot"])
            assert not verify(row, page, SCHEMA, saved)
            assert row.evidence["/published"].quote == row.record["published"]


async def test_three_tool_entries_stop_even_when_reported_billable_count_fits(replay):
    config, replies, requests, visited, _ = replay
    replies.append(openai_reply([FIRST, SECOND], actions=3, billed=2, tokens=13383))
    with pytest.raises(SearchUnavailableError, match=r"entries: 3; requested limit: 2; .*: 2"):
        await arun(goal=GOAL, schema=SCHEMA, task=task(), config=config)
    assert len(requests) == 1 and not visited
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        saved = store.load(None)
        assert saved["status"] == "PAUSED"
        assert not store.events(saved["id"], "seed_frontier")
        report = store.events(saved["id"], "search_request")[-1]["payload"]
        assert (report["tool_actions"], report["billable_searches"], report["reported_tokens"]) == (
            3,
            2,
            13383,
        )


async def test_missing_and_ambiguous_sources_never_start_the_browser(replay):
    config, replies, requests, visited, _ = replay
    config.search_request_budget = 3
    replies.extend(
        [
            openai_reply([FIRST]),
            openai_reply([FIRST, f"{ORIGIN}/releases/2022/atlas/", SECOND]),
            openai_reply([FIRST, SECOND]),
        ]
    )
    with pytest.raises(VerboisyError, match="did not find every") as error:
        await arun(goal=GOAL, schema=SCHEMA, task=task(), config=config)
    run_id = error.value.details["run_id"]
    with pytest.raises(VerboisyError, match="ambiguous sources"):
        await arun(resume=run_id, config=config)
    assert not visited
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert not store.events(run_id, "initial_query_result")
        assert not store.events(run_id, "initial_discovery_result")
        assert not store.pages(run_id)
    result = await arun(resume=run_id, config=config, max_steps=2)
    assert result.completed and len(requests) == 3


async def test_resume_reuses_checkpoint_and_validates_published_acquisition(replay, monkeypatch):
    config, replies, requests, visited, _ = replay
    replies.append(openai_reply([FIRST, SECOND]))
    original = ResearchStore.event

    def interrupt(self, rid, kind, payload):
        if kind == "initial_discovery_result":
            raise OSError("Interrupted before acquiring the source set")
        return original(self, rid, kind, payload)

    with monkeypatch.context() as context:
        context.setattr(ResearchStore, "event", interrupt)
        with pytest.raises(OSError, match="Interrupted"):
            await arun(goal=GOAL, schema=SCHEMA, task=task(), config=config)
    assert not visited
    result = await arun(resume=True, config=config, max_steps=2)
    assert result.completed
    assert len(requests) == 1
    exported = await arun(resume=result.run_id, config=config)
    assert exported.completed and exported.records == result.records
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        event = store.events(result.run_id, "initial_discovery_result")[-1]["payload"]
        event["seeds"] = [SECOND, FIRST]
        store.event(result.run_id, "initial_discovery_result", event)
    with pytest.raises(VerboisyError, match="does not match its selected sources"):
        await arun(resume=result.run_id, config=config)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "corruption", ["no_acquisition", "no_observation", "changed_query", "changed_selection"]
)
async def test_resume_rejects_an_unbound_or_changed_acquisition(replay, corruption):
    config, replies, requests, visited, _ = replay
    replies.append(openai_reply([FIRST, SECOND]))
    result = await arun(goal=GOAL, schema=SCHEMA, task=task(), config=config, max_steps=2)
    assert result.completed
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        event = store.events(result.run_id, "initial_discovery_result")[-1]["payload"]
        if corruption == "no_acquisition":
            store.db.execute(
                "DELETE FROM events WHERE run_id=? AND kind='initial_discovery_result'",
                (result.run_id,),
            )
            store.db.commit()
        else:
            if corruption == "no_observation":
                event["observations"] = []
            elif corruption == "changed_query":
                event["observations"][0]["query"] = "different goal"
            else:
                replacement = f"{ORIGIN}/releases/2026/atlas/"
                event["seeds"][0] = replacement
                event["observations"][0]["results"][0]["url"] = replacement
            store.event(result.run_id, "initial_discovery_result", event)
    with pytest.raises(
        VerboisyError, match="HTML metadata .* (saved discovery|its task|its selected sources)"
    ):
        await arun(resume=result.run_id, config=config)
    assert len(requests) == 1
    assert visited == [FIRST, SECOND]


async def test_query_checkpoint_cannot_be_reassigned_to_another_goal(replay):
    config, _, requests, visited, _ = replay
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        rid = store.create(GOAL, SCHEMA, task(), None)
        store.event(rid, "initial_discovery", {"status": "pending"})
        store.event(
            rid,
            "initial_query_result",
            {
                "query": "different goal",
                "observation": {
                    "query": QUERY,
                    "provider": "openai",
                    "results": [{"title": "Source", "url": url} for url in [FIRST, SECOND]],
                },
            },
        )
    with pytest.raises(VerboisyError, match="query does not match"):
        await arun(resume=rid, config=config)
    assert not requests and not visited


async def test_cannot_count_a_redirect_to_another_approved_page(replay):
    config, replies, _, visited, redirects = replay
    replies.append(openai_reply([FIRST, SECOND]))
    redirects[FIRST] = SECOND
    result = await arun(goal=GOAL, schema=SCHEMA, task=task(), config=config, max_steps=2)
    assert visited == [FIRST, SECOND]
    assert not result.completed
    assert [row["title"] for row in result.records] == [EXPECTED[1]["title"]]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"allowed_hosts": []}, "one explicit HTTPS host"),
        ({"allowed_hosts": [HOST, "mirror.example.test"]}, "one explicit HTTPS host"),
        ({"allowed_hosts": ["x" * 251 + ".test"]}, "canonical DNS host"),
        ({"allowed_hosts": ["local"]}, "canonical DNS host"),
        ({"allowed_hosts": ["192.0.2.8"]}, "canonical DNS host"),
        ({"allowed_hosts": [HOST.upper()]}, "canonical DNS host"),
        ({"include_paths": []}, "one target per path"),
        ({"include_paths": [f"/release/{i}/" for i in range(11)]}, "one target per path"),
        ({"include_paths": ["/same", "/same"]}, "one target per path"),
        ({"target_records": 1}, "one target per path"),
        ({"max_pages": 1}, "one target per path"),
        ({"exclude_paths": ["//other.example.test"]}, "one target per path"),
        ({"avoided_hosts": ["example.test"]}, "conflicts with the source policy"),
        ({"seed_urls": [SECOND, FIRST]}, "declared order"),
    ],
)
def test_scope_requires_an_explicit_unambiguous_contract(changes, message):
    with pytest.raises(VerboisyError, match=message):
        validate_research_contract(SCHEMA, task(**changes))


def test_one_url_cannot_satisfy_multiple_selectors():
    spec = task(include_paths=["/releases/*", "/releases/*/atlas/"])
    with pytest.raises(VerboisyError, match="ambiguous sources"):
        MetadataSourceScope.from_task(spec).select([FIRST])


def test_boundaries_preserve_only_canonical_https_urls():
    scope = MetadataSourceScope.from_task(task())
    for url in (
        FIRST.replace("https:", "http:"),
        FIRST.replace(HOST, f"{HOST}:8443"),
        f"{FIRST}#/route",
        f"{FIRST}#stripped",
        f"{ORIGIN}/releases/20%2F21/atlas/",
        f"{ORIGIN}/releases/20%5c21/atlas/",
    ):
        with pytest.raises(VerboisyError, match="outside its scope"):
            scope.select([url])


async def test_opt_in_does_not_override_legacy_requirements_or_cli_restrictions(replay):
    config, _, requests, visited, _ = replay
    with pytest.raises(VerboisyError, match="Invalid task"):
        await arun(goal=GOAL, schema=SCHEMA, task={"html_metadata_discovery": True}, config=config)
    with pytest.raises(VerboisyError, match="cannot be combined with explicit seeds"):
        await arun(goal=GOAL, schema=SCHEMA, task=task(seed_urls=[FIRST, SECOND]), config=config)
    with pytest.raises(VerboisyError, match="conflicts with the source policy"):
        await arun(
            goal=GOAL,
            schema=SCHEMA,
            task=task(),
            config=config,
            include=["mirror.example.test"],
            onlyinclude=True,
        )
    assert not requests and not visited
    assert "html_metadata_discovery" not in task(html_metadata_discovery=False).model_dump()
