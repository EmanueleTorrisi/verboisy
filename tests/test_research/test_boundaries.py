# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Failure boundaries, first-use setup and CLI status contracts."""

import asyncio
import importlib
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner
from verboisy import arun, run
from verboisy.api import RunResult, _export_path, _json
from verboisy.browser.provision import _install, ensure_browser
from verboisy.core.research import ResearchRunner
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.evidence.models import Candidate, FieldRule, Proof, TaskSpec
from verboisy.evidence.snapshot import chunks, snapshot
from verboisy.evidence.verify import lookup, verify
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import NavigationError, VerboisyError

from tests.test_research.test_contracts import SCHEMA, task


async def test_provision_cache_install_and_offline(tmp_path, monkeypatch):
    path = tmp_path / "browser" / "bin" / "chrome"
    with pytest.raises(NavigationError, match="disabled"):
        await ensure_browser(str(path), False)

    def install(command, **_kwargs):
        assert command[-3:] == ["playwright", "install", "chromium"]
        path.parent.mkdir(parents=True)
        path.touch()
        return SimpleNamespace(returncode=0)

    process = Mock(side_effect=install)
    monkeypatch.setattr("subprocess.run", process)
    await ensure_browser(str(path), True)
    await ensure_browser(str(path), True)
    _install(path)
    assert process.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        OSError("secret"),
        subprocess.TimeoutExpired("x", 1),
        SimpleNamespace(returncode=1),
        SimpleNamespace(returncode=0),
    ],
)
async def test_failed_download_never_reports_ready(tmp_path, monkeypatch, failure):
    process = (
        Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    )
    monkeypatch.setattr("subprocess.run", process)
    with pytest.raises(NavigationError) as exc:
        await ensure_browser(str(tmp_path / "browser" / "bin" / "chrome"), True)
    assert "secret" not in str(exc.value)


def test_cli_exit_codes_and_redaction(monkeypatch, tmp_path):
    cli = importlib.import_module("verboisy.cli.main")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    for status, code in [("COMPLETED", 0), ("PAUSED", 2), ("FAILED", 1)]:
        result = RunResult(
            "test",
            [],
            tmp_path / "data.json",
            tmp_path / "db",
            status == "COMPLETED",
            status,
            "reason",
        )
        mocked = Mock(return_value=result)
        monkeypatch.setattr(cli, "run", mocked)
        answer = runner.invoke(cli.app, ["run", "--resume"])
        assert answer.exit_code == code and "test" in answer.output
        assert mocked.call_args.kwargs["resume"] is True
    for error, code in [
        (KeyboardInterrupt(), 130),
        (VerboisyError("safe error"), 1),
        (RuntimeError("SECRET"), 1),
        (
            ValidationError.from_exception_data(
                "Settings", [{"type": "int_parsing", "loc": ("max_steps",), "input": "SECRET"}]
            ),
            1,
        ),
    ]:
        monkeypatch.setattr(cli, "run", Mock(side_effect=error))
        answer = runner.invoke(cli.app, ["run", "--resume", "an-id"])
        assert answer.exit_code == code and "SECRET" not in answer.output
    assert runner.invoke(cli.app, ["doctor"]).exit_code == 0
    browser = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr("verboisy.browser.context.BrowserManager", lambda *_a: browser)
    assert runner.invoke(cli.app, ["setup"]).exit_code == 0
    browser.start.side_effect = NavigationError("setup failed")
    assert runner.invoke(cli.app, ["setup"]).exit_code == 1


async def test_source_discovery_task_files_and_collection_limits(
    config, world, monkeypatch, tmp_path
):
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA))
    config.search_provider = "disabled"
    with pytest.raises(VerboisyError, match="disabled"):
        await arun(goal="Find customers", schema=schema, config=config)
    config.search_provider = "brave"
    search = AsyncMock(
        return_value=SearchObservation(
            provider="brave",
            query="customers",
            results=[
                SearchResult(
                    title="leads",
                    url="https://people.test/",
                )
            ],
        )
    )
    monkeypatch.setattr("verboisy.api.web_search", search)
    result = await arun(
        goal="Find customers",
        schema=schema,
        task={"target_records": 2, "settle_ms": 0},
        headless=False,
        config=config,
    )
    assert result.completed and search.await_count == 1
    result = await arun(
        goal="Find at https://people.test/.", schema=schema, config=config, max_steps=1
    )
    assert not result.completed
    spec = tmp_path / "task.json"
    spec.write_text(json.dumps(task()))
    target = tmp_path / "bad.json"
    target.mkdir()
    with pytest.raises(VerboisyError, match="Export failed"):
        await arun(goal="Find", schema=schema, task=spec, export=target, config=config)
    with pytest.raises(VerboisyError, match="Target conflicts"):
        await arun(goal="Find", schema={**SCHEMA, "minItems": 3}, task=task(), config=config)
    empty = tmp_path / "not-object.json"
    empty.write_text("[]")
    with pytest.raises(VerboisyError, match="object"):
        _json(empty)
    with pytest.raises(VerboisyError, match="differ"):
        _export_path(tmp_path / "db.json", str(tmp_path / "db.json"))


def test_sync_api_routes_same_implementation(config, world):
    result = run(goal="Find", schema=SCHEMA, task=task(), config=config)
    assert result.completed


async def test_cancel_checkpoint_and_invalid_proposals(config, world, monkeypatch):
    monkeypatch.setattr(
        "verboisy.llm.client.LLMClient.complete_json",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
    store = ResearchStore(config.sqlite_db_path)
    state = store.load(None)
    assert state["reason"] == "interrupted"
    store.close()
    monkeypatch.setattr(
        "verboisy.llm.client.LLMClient.complete_json", AsyncMock(return_value={"action": "FINISH"})
    )
    result = await arun(resume=state["id"], config=config)
    assert not result.completed and result.stop_reason == "coverage_or_identity_gaps"


async def test_oversized_blocks_are_explicit(config, world):
    config.max_dom_chars = 1
    result = await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
    assert result.stop_reason == "coverage_or_identity_gaps"


@pytest.mark.parametrize("mode", ["unchanged", "absent", "disabled", "limit"])
async def test_bounded_pagination(config, world, mode):
    page = await world.get_page()
    control = SimpleNamespace(
        count=AsyncMock(return_value=0 if mode == "absent" else 1),
        is_visible=AsyncMock(return_value=True),
        is_enabled=AsyncMock(return_value=mode != "disabled"),
        click=AsyncMock(),
    )
    page.locator.return_value = control
    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(
            target_records=3,
            pagination_selector="#next",
            max_interactions_per_page=0 if mode == "limit" else 2,
        ),
        config=config,
    )
    assert not result.completed
    assert control.click.await_count <= 3
    if mode == "limit":
        assert result.stop_reason == "coverage_or_identity_gaps"


def test_remaining_grounding_boundaries():
    page = snapshot("<p>10 true</p>", "https://data.test/")
    c = Candidate(
        scope="page",
        record={"x": 10},
        evidence={"/x": Proof(source=page.sources[0].id, quote="10", transform="integer")},
    )
    assert verify(
        c, page, {"type": "object", "properties": {"x": {"type": "string"}}}, TaskSpec()
    ) == ["schema_invalid"]
    assert verify(
        Candidate(scope="page", record={"x": None}, evidence={}),
        page,
        {"type": "object"},
        TaskSpec(),
    ) == ["empty_record"]
    c.evidence["/extra"] = c.evidence["/x"]
    assert "unknown_evidence_pointer" in verify(c, page, {"type": "object"}, TaskSpec())
    assert "/x:expected_page_url" in verify(
        c, page, {"type": "object"}, TaskSpec(field_rules={"/x": FieldRule(source="page_url")})
    )
    c.record["x"] = None
    assert verify(c, page, {"type": "object"}, TaskSpec(identity_fields=["/x"]))
    with pytest.raises(ValueError):
        lookup({}, "bad")
    # A single large scope is split without omitting admitted tail evidence.
    long = snapshot("<p>" + ("a " * 10) + "</p><p>" + ("b " * 10) + "</p>", "https://data.test/")
    assert len(chunks(long, 110)) == 2


async def test_redirect_scope_invalid_review_and_recover_saved_target(config, world, monkeypatch):
    page = await world.get_page()

    async def redirect(_url):
        page.url = "https://outside.test/"
        page.evaluate.return_value = {
            "url": page.url,
            "html": "<p>Outside</p>",
            "visible_html": "<p>Outside</p>",
            "oversized": False,
        }

    original = world.navigate_to.side_effect
    world.navigate_to.side_effect = redirect
    result = await arun(goal="Find", schema=SCHEMA, task=task(), config=config, max_steps=1)
    assert not result.completed
    world.navigate_to.side_effect = original
    invalid = ValidationError.from_exception_data(
        "Review", [{"type": "missing", "loc": ("relevant",), "input": {}}]
    )
    with monkeypatch.context() as patcher:
        patcher.setattr(
            "verboisy.extractor.evidenced.EvidenceExtractor.check", AsyncMock(side_effect=invalid)
        )
        rejected = await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
        assert not rejected.records
    good = await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
    store = ResearchStore(config.sqlite_db_path)
    # Simulates interruption after acceptance transaction and before completion checkpoint.
    store.finish(good.run_id, "PAUSED", "interrupted", 12, 50)
    runner = ResearchRunner(store, good.run_id, config)
    runner.account()
    assert store.load(good.run_id)["tokens"] == 12
    assert await runner.run(1) == ("COMPLETED", "target_met")
    store.close()


def test_empty_snapshot_and_missing_entity_identity():
    page = snapshot(
        '<div hidden><span hidden>hide</span></div><p style="color:red">A</p>', "https://x.test/"
    )
    assert [s.text for s in page.sources] == ["A"]
    assert chunks(snapshot("<body></body>", "https://x.test/"), 100) == []
    c = Candidate(
        scope="page",
        record={"id": None, "name": "A"},
        evidence={"/name": Proof(source=page.sources[0].id, quote="A")},
    )
    assert "/id:invalid_identity" in verify(
        c, page, {"type": "object"}, TaskSpec(identity_fields=["/id"])
    )


async def test_spreadsheet_export(config, world, tmp_path):
    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(csv_mode="spreadsheet"),
        export=tmp_path / "sheet.csv",
        config=config,
    )
    assert "Alice,31" in result.export_path.read_text()


def test_sql_connection_error_releases_lock(tmp_path, monkeypatch):
    from filelock import FileLock

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "verboisy.storage.research.sqlite3.connect",
            Mock(side_effect=OSError("disk unavailable")),
        )
        with pytest.raises(OSError):
            ResearchStore(str(tmp_path / "db"))
    lock = FileLock(str(tmp_path / "db") + ".lock")
    with lock.acquire(timeout=0):
        pass


def test_cli_without_export(monkeypatch, tmp_path):
    cli = importlib.import_module("verboisy.cli.main")
    monkeypatch.setattr(
        cli,
        "run",
        Mock(
            return_value=RunResult("id", [], None, tmp_path / "db", True, "COMPLETED", "target_met")
        ),
    )
    assert CliRunner().invoke(cli.app, ["run", "--resume", "id"]).exit_code == 0


async def test_oversized_page_fails_before_a_model_call(config, world, monkeypatch):
    config.max_page_bytes = 1
    request = AsyncMock()
    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", request)
    result = await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
    assert not result.completed
    request.assert_not_awaited()


async def test_browser_side_size_limit_stops_before_transfer(config, world, monkeypatch):
    page = await world.get_page()
    page.evaluate.side_effect = lambda *_args: {"oversized": True}
    request = AsyncMock()
    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", request)
    result = await arun(goal="Find", schema=SCHEMA, task=task(), config=config)
    assert result.stop_reason == "source_failures"
    request.assert_not_awaited()


async def test_macos_provision_lock_is_outside_app_bundle(tmp_path, monkeypatch):
    revision = tmp_path / "chromium-1234"
    path = revision / "chrome-mac/Chrome.app/Contents/MacOS/Chrome"

    def install(*_args, **_kwargs):
        assert not revision.exists()
        assert (tmp_path / "chromium-1234.verboisy-install.lock").exists()
        path.parent.mkdir(parents=True)
        path.touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", install)
    await ensure_browser(str(path), True)


async def test_invalid_model_response_becomes_coverage_gap_not_provider_failure(
    config, world, monkeypatch
):
    from verboisy.utils.exceptions import LLMResponseError

    monkeypatch.setattr(
        "verboisy.llm.client.LLMClient.complete_json",
        AsyncMock(side_effect=LLMResponseError("invalid response")),
    )

    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(),
        config=config,
    )

    assert not result.completed
    assert result.stop_reason == "coverage_or_identity_gaps"

    store = ResearchStore(config.sqlite_db_path)
    summary = store.summary(result.run_id)

    assert summary["coverage_gaps"] > 0
    assert summary["pages"].get("done", 0) > 0

    store.close()


async def test_invalid_review_response_becomes_coverage_gap(config, world, monkeypatch):
    from verboisy.utils.exceptions import LLMResponseError

    review = AsyncMock(side_effect=LLMResponseError("invalid review response"))

    monkeypatch.setattr(
        "verboisy.extractor.evidenced.EvidenceExtractor.check",
        review,
    )

    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(),
        config=config,
    )

    assert not result.completed
    assert result.stop_reason == "coverage_or_identity_gaps"
    assert review.await_count > 0

    store = ResearchStore(config.sqlite_db_path)
    summary = store.summary(result.run_id)

    assert summary["coverage_gaps"] > 0
    assert not store.records(result.run_id)

    store.close()


async def test_invalid_proposal_response_defers_discovered_links(config, world, monkeypatch):
    from verboisy.utils.exceptions import LLMResponseError

    proposal = AsyncMock(side_effect=LLMResponseError("invalid response"))

    monkeypatch.setattr(
        "verboisy.extractor.evidenced.EvidenceExtractor.propose",
        proposal,
    )

    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(max_pages=1),
        config=config,
    )

    assert not result.completed
    assert result.stop_reason == "page_budget"

    store = ResearchStore(config.sqlite_db_path)

    rows = store.db.execute(
        """
        SELECT url, status, parent_url
        FROM pages
        WHERE run_id = ?
        ORDER BY id
        """,
        (result.run_id,),
    ).fetchall()

    pages = {row[0]: (row[1], row[2]) for row in rows}

    assert pages["https://people.test/"][0] == "done"
    assert pages["https://people.test/a"] == (
        "deferred",
        "https://people.test/",
    )
    assert pages["https://people.test/b"] == (
        "deferred",
        "https://people.test/",
    )

    store.close()

    assert proposal.await_count > 0


async def test_interruption_preserves_accepted_record_and_resume_deduplicates(
    config, world, monkeypatch
):
    original_accept = ResearchStore.accept
    interrupted = False

    def interrupt_after_first_accept(self, *args, **kwargs):
        nonlocal interrupted

        outcome = original_accept(self, *args, **kwargs)

        if outcome == "accepted" and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()

        return outcome

    monkeypatch.setattr(
        ResearchStore,
        "accept",
        interrupt_after_first_accept,
    )

    with pytest.raises(asyncio.CancelledError):
        await arun(
            goal="Find",
            schema=SCHEMA,
            task=task(),
            config=config,
        )

    store = ResearchStore(config.sqlite_db_path)
    state = store.load(None)

    assert state["reason"] == "interrupted"

    before = store.records(state["id"])
    assert len(before) == 1

    first_record = before[0]
    store.close()

    resumed = await arun(
        resume=state["id"],
        config=config,
    )

    assert resumed.completed
    assert resumed.stop_reason == "target_met"

    assert [{k: v for k, v in row.items() if k != "id"} for row in resumed.records] == [
        {"customer": "Alice", "age": 31},
        {"customer": "Bob", "age": 22},
    ]
    assert all(row["id"] for row in resumed.records)

    assert {key: value for key, value in first_record.items() if key != "id"} == {
        key: value for key, value in resumed.records[0].items() if key != "id"
    }

    assert [row["id"] for row in resumed.records] == [1, 2]
    assert len(resumed.records) == len({record["customer"] for record in resumed.records})


async def test_runner_deduplicates_same_identity_same_payload(config, world, monkeypatch):
    from verboisy.evidence.models import Candidate, PageProposal
    from verboisy.extractor.evidenced import EvidenceExtractor

    async def propose(self, page, sources):
        record = {"customer": "same-id", "age": 31}
        candidate = Candidate(
            scope="page",
            record=record,
            evidence={},
        )
        return PageProposal(
            candidates=[candidate],
            priority_links=[],
        )

    async def check(self, candidate, page):
        return []

    monkeypatch.setattr(EvidenceExtractor, "propose", propose)
    monkeypatch.setattr(EvidenceExtractor, "check", check)

    result = await arun(
        goal="Collect records",
        schema=SCHEMA,
        task=task(
            seed_urls=[
                "https://people.test/a",
                "https://people.test/b",
            ],
            allowed_hosts=["people.test"],
            target_records=2,
            identity_fields=["/customer"],
            max_depth=0,
            max_pages=2,
        ),
        config=config,
    )

    assert not result.completed
    assert [{k: v for k, v in row.items() if k != "id"} for row in result.records] == [
        {"customer": "same-id", "age": 31}
    ]
    assert result.records[0]["id"]

    store = ResearchStore(config.sqlite_db_path)

    outcomes = [
        row[0]
        for row in store.db.execute(
            """
            SELECT json_extract(payload, '$.outcome')
            FROM events
            WHERE run_id = ? AND kind = 'candidate'
            ORDER BY id
            """,
            (result.run_id,),
        )
    ]

    assert outcomes == ["accepted", "duplicate"]
    assert store.summary(result.run_id)["identity_conflicts"] == 0

    store.close()


async def test_runner_invalidates_conflicting_identity(config, world, monkeypatch):
    from verboisy.evidence.models import Candidate, PageProposal
    from verboisy.extractor.evidenced import EvidenceExtractor

    async def propose(self, page, sources):
        age = 31 if page.url.endswith("/a") else 32

        candidate = Candidate(
            scope="page",
            record={"customer": "same-id", "age": age},
            evidence={},
        )

        return PageProposal(
            candidates=[candidate],
            priority_links=[],
        )

    async def check(self, candidate, page):
        return []

    monkeypatch.setattr(EvidenceExtractor, "propose", propose)
    monkeypatch.setattr(EvidenceExtractor, "check", check)

    result = await arun(
        goal="Collect records",
        schema=SCHEMA,
        task=task(
            seed_urls=[
                "https://people.test/a",
                "https://people.test/b",
            ],
            allowed_hosts=["people.test"],
            target_records=2,
            identity_fields=["/customer"],
            max_depth=0,
            max_pages=10,
        ),
        config=config,
    )

    assert not result.completed
    assert result.stop_reason == "coverage_or_identity_gaps"
    assert result.records == []

    store = ResearchStore(config.sqlite_db_path)

    outcomes = [
        row[0]
        for row in store.db.execute(
            """
            SELECT json_extract(payload, '$.outcome')
            FROM events
            WHERE run_id = ? AND kind = 'candidate'
            ORDER BY id
            """,
            (result.run_id,),
        )
    ]

    assert outcomes == ["accepted", "rejected"]
    assert store.summary(result.run_id)["identity_conflicts"] == 1

    store.close()


async def test_avoided_host_is_blocked_by_runner(config, world):
    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(avoided_hosts=["people.test"]),
        config=config,
    )
    assert not result.completed
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id)["pages"] == {"blocked": 1}
    finally:
        store.close()


async def test_redirect_outside_allowed_host_is_navigation_failure(config, world):
    page = await world.get_page()
    original = page.evaluate.side_effect

    async def redirected(*args, **kwargs):
        observation = await original(*args, **kwargs) if original else page.evaluate.return_value
        return {**observation, "url": "https://outside.test/"}

    page.evaluate.side_effect = redirected
    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(allowed_hosts=["people.test"]),
        config=config,
    )
    assert result.status == "FAILED" and result.stop_reason == "source_failures"


async def test_provider_rate_limit_pauses_research(
    config,
    world,
    monkeypatch,
):
    from verboisy.utils.exceptions import (
        LLMRateLimitError,
    )

    async def rate_limited(
        _self,
        _system,
        _prompt,
    ):
        raise LLMRateLimitError("OpenAI rate limit reached")

    monkeypatch.setattr(
        "verboisy.llm.client.LLMClient.complete_json",
        rate_limited,
    )

    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(),
        config=config,
    )

    assert result.status == "PAUSED"
    assert result.stop_reason == "provider_rate_limit"


@pytest.mark.asyncio
async def test_adaptive_probe_stops_unproductive_page(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import verboisy.core.research as research
    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                }
            },
        },
    }

    captured = MagicMock()
    captured.id = "snapshot-1"
    captured.url = "https://example.test/"
    captured.sources = []
    captured.truncated = False
    captured.model_copy.return_value = captured

    monkeypatch.setattr(
        research,
        "snapshot",
        lambda *_args, **_kwargs: captured,
    )

    batch_sources = []

    for index in range(3):
        source = MagicMock()
        source.model_dump.return_value = {
            "id": f"source-{index}",
            "text": "unrelated evidence",
        }
        batch_sources.append(source)

    batches = [
        [batch_sources[0]],
        [batch_sources[1]],
        [batch_sources[2]],
    ]

    monkeypatch.setattr(
        research,
        "chunks",
        lambda *_args, **_kwargs: batches,
    )

    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "oversized": False,
                "url": "https://example.test/",
                "html": "<html>data</html>",
                "visible_html": "<html>data</html>",
            }
        )
    )

    runner = object.__new__(ResearchRunner)

    runner.rid = "run-1"
    runner.schema = schema
    runner.task = SimpleNamespace(
        settle_ms=0,
    )
    runner.config = SimpleNamespace(
        max_page_bytes=100_000,
        max_snapshot_chars=100_000,
        max_dom_chars=10_000,
    )

    runner.plan = build_research_plan(
        schema,
        5,
    )
    runner.adaptive_frontier = True
    runner.source_productivity = {}

    runner.browser = SimpleNamespace(
        navigate_to=AsyncMock(),
        get_page=AsyncMock(return_value=page),
    )

    # Three rejected candidates per batch:
    # after batch 2 => 6 rejects, exceeding the cutoff of 5.
    proposal = SimpleNamespace(
        priority_links=[],
        candidates=[
            object(),
            object(),
            object(),
        ],
    )

    runner.extractor = SimpleNamespace(
        propose=AsyncMock(return_value=proposal),
        check=AsyncMock(return_value=["unsupported_value"]),
    )

    runner.store = SimpleNamespace(
        snapshot=MagicMock(),
        accept=MagicMock(return_value="rejected"),
        event=MagicMock(),
        mark_page=MagicMock(),
    )

    runner.in_scope = MagicMock(return_value=True)
    runner.target_met = MagicMock(return_value=False)
    runner.discover = MagicMock()

    await runner.process(
        {
            "id": 123,
            "url": "https://example.test/",
            "depth": 0,
        }
    )

    # The third chunk must never incur a model call.
    assert runner.extractor.propose.await_count == 2

    runner.store.event.assert_any_call(
        "run-1",
        "adaptive_probe_stop",
        {
            "page": "snapshot-1",
            "url": "https://example.test/",
            "batches_seen": 2,
            "accepted": 0,
            "rejected": 6,
            "probe_batches": 2,
            "rejection_cutoff": 5,
        },
    )

    runner.discover.assert_called_once_with(
        captured,
        0,
        [],
        productive=False,
    )

    runner.store.mark_page.assert_called_once_with(
        123,
        "done",
        "adaptive_probe_limit",
    )


def test_adaptive_batch_ranking_prefers_schema_relevant_evidence():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                },
                "capital": {
                    "type": "string",
                },
                "population_count": {
                    "type": "integer",
                },
                "area_amount": {
                    "type": "number",
                },
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.plan = build_research_plan(
        schema,
        5,
    )

    navigation = MagicMock()
    navigation.model_dump.return_value = {
        "id": "nav",
        "text": "Home About Contact Privacy",
    }

    useful = MagicMock()
    useful.model_dump.return_value = {
        "id": "records",
        "text": ("Country name capital population " "area statistics table"),
    }

    ranked = runner.rank_batches(
        [
            [navigation],
            [useful],
        ]
    )

    assert ranked[0][0] is useful
    assert ranked[1][0] is navigation


def test_adaptive_batch_ranking_preserves_order_on_ties():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "population": {
                    "type": "integer",
                }
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.plan = build_research_plan(
        schema,
        5,
    )

    first = MagicMock()
    first.model_dump.return_value = {
        "text": "ordinary unrelated content",
    }

    second = MagicMock()
    second.model_dump.return_value = {
        "text": "different unrelated content",
    }

    ranked = runner.rank_batches(
        [
            [first],
            [second],
        ]
    )

    assert ranked[0][0] is first
    assert ranked[1][0] is second


def test_source_productivity_ignores_hostless_url():
    from unittest.mock import MagicMock

    from verboisy.core.research import ResearchRunner

    runner = object.__new__(ResearchRunner)
    runner.rid = "run-1"
    runner.source_productivity = {}
    runner.store = MagicMock()

    runner.record_source_productivity(
        "not-a-url",
        accepted=1,
        rejected=0,
        duplicates=0,
    )

    assert runner.source_productivity == {}
    runner.store.event.assert_not_called()


@pytest.mark.asyncio
async def test_playwright_error_fails_page_not_run():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from playwright.async_api import Error as PlaywrightError
    from verboisy.core.research import ResearchRunner

    runner = object.__new__(ResearchRunner)

    runner.rid = "run-1"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        summary=MagicMock(
            return_value={
                "pages": {},
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value={
                "id": 7,
                "url": "https://example.test/",
                "depth": 0,
            }
        ),
        mark_page=MagicMock(),
        event=MagicMock(),
        finish=MagicMock(),
    )

    runner.source_scores = MagicMock(return_value={})
    runner.target_met = MagicMock(return_value=False)
    runner.process = AsyncMock(side_effect=PlaywrightError("page execution context disappeared"))

    status, reason = await runner.run(max_steps=1)

    assert (status, reason) == (
        "PAUSED",
        "page_budget",
    )

    runner.store.mark_page.assert_called_once_with(
        7,
        "failed",
        "browser_error",
    )

    runner.store.event.assert_called_once_with(
        "run-1",
        "page_failure",
        {
            "page_id": 7,
            "reason": "browser_error",
            "error_type": "Error",
        },
    )


@pytest.mark.asyncio
async def test_bounded_run_rebalances_frontier_after_recovery():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from verboisy.core.research import ResearchRunner

    runner = object.__new__(ResearchRunner)

    runner.rid = "run-1"
    runner.adaptive_frontier = True

    runner.task = SimpleNamespace(
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.frontier_batch_size = MagicMock(
        return_value=15,
    )
    runner.source_scores = MagicMock(
        return_value={},
    )
    runner.target_met = MagicMock(
        return_value=True,
    )

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        rebalance_frontier=MagicMock(
            return_value={
                "queued": 15,
                "demoted": 307,
            }
        ),
        event=MagicMock(),
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "COMPLETED",
        "target_met",
    )

    assert runner.store.recover.call_count == 2
    runner.store.recover.assert_any_call("run-1")
    runner.store.rebalance_frontier.assert_called_once_with(
        "run-1",
        15,
    )
    runner.store.event.assert_called_once_with(
        "run-1",
        "frontier_rebalance",
        {
            "queued": 15,
            "demoted": 307,
        },
    )


def test_adaptive_scope_windowing_limits_entity_work_and_preserves_evidence():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import Source, TaskSpec

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "capital": {"type": "string"},
                "population_count": {"type": "integer"},
                "area_amount": {"type": "number"},
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.rid = "run-1"
    runner.task = TaskSpec(target_records=5)
    runner.plan = build_research_plan(schema, 5)
    runner.store = MagicMock()
    runner.store.records.return_value = []

    page_sources = [
        Source(
            id="page-header",
            kind="text",
            text="capital population area",
            scope="page",
        ),
        Source(
            id="page-prose",
            kind="text",
            text="A broad page description that is not an entity.",
            scope="page",
        ),
    ]

    entity_sources = []

    for row in range(12):
        scope = f"s{row}"

        for column in range(4):
            entity_sources.append(
                Source(
                    id=f"e-{row}-{column}",
                    kind="text",
                    text=f"value-{row}-{column}",
                    scope=scope,
                )
            )

    original = page_sources + entity_sources
    windowed = runner.window_batches([original])

    assert len(windowed) == 3

    first_scopes = {source.scope for source in windowed[0] if source.scope != "page"}
    second_scopes = {source.scope for source in windowed[1] if source.scope != "page"}

    assert len(first_scopes) == 10
    assert len(second_scopes) == 2
    assert windowed[-1] == page_sources

    original_ids = {source.id for source in original}
    windowed_ids = {source.id for batch in windowed for source in batch}

    assert windowed_ids == original_ids


def test_batch_ranking_prefers_repeated_entity_scopes_over_page_prose():
    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import Source

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "capital": {"type": "string"},
                "population_count": {"type": "integer"},
                "area_amount": {"type": "number"},
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.plan = build_research_plan(schema, 5)

    page_batch = [
        Source(
            id="page",
            kind="text",
            text="name capital population area statistics table dataset",
            scope="page",
        )
    ]

    entity_batch = []

    for row in range(10):
        for column in range(2):
            entity_batch.append(
                Source(
                    id=f"e-{row}-{column}",
                    kind="text",
                    text=f"value-{row}-{column}",
                    scope=f"s{row}",
                )
            )

    ranked = runner.rank_batches(
        [
            page_batch,
            entity_batch,
        ]
    )

    assert ranked[0] is entity_batch
    assert ranked[1] is page_batch


def test_adaptive_scope_windowing_leaves_small_batches_unchanged():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import Source, TaskSpec

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.rid = "run-1"
    runner.task = TaskSpec(target_records=5)
    runner.plan = build_research_plan(schema, 5)
    runner.store = MagicMock()
    runner.store.records.return_value = []

    batch = [
        Source(
            id="page",
            kind="text",
            text="Countries",
            scope="page",
        ),
        Source(
            id="a1",
            kind="text",
            text="Canada",
            scope="s1",
        ),
        Source(
            id="a2",
            kind="text",
            text="Ottawa",
            scope="s1",
        ),
        Source(
            id="b1",
            kind="text",
            text="China",
            scope="s2",
        ),
        Source(
            id="b2",
            kind="text",
            text="Beijing",
            scope="s2",
        ),
    ]

    result = runner.window_batches([batch])

    assert result == [batch]
    assert result[0] is batch


def test_adaptive_scope_windowing_skips_bad_page_context_but_preserves_it():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import Source, TaskSpec

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.rid = "run-1"
    runner.task = TaskSpec(target_records=5)
    runner.plan = build_research_plan(schema, 5)
    runner.store = MagicMock()
    runner.store.records.return_value = []

    blank = Source(
        id="blank",
        kind="text",
        text=" ",
        scope="page",
    )
    oversized = Source(
        id="oversized",
        kind="text",
        text="x" * 161,
        scope="page",
    )
    useful_context = Source(
        id="context",
        kind="text",
        text="Country name",
        scope="page",
    )

    entities = [
        Source(
            id=f"e-{index}",
            kind="text",
            text=f"Country {index}",
            scope=f"s{index}",
        )
        for index in range(11)
    ]

    result = runner.window_batches(
        [
            [
                blank,
                oversized,
                useful_context,
                *entities,
            ]
        ]
    )

    assert useful_context in result[0]
    assert blank not in result[0]
    assert oversized not in result[0]

    assert result[-1] == [
        blank,
        oversized,
        useful_context,
    ]


def test_adaptive_scope_windowing_handles_large_batch_without_page_fallback():
    from unittest.mock import MagicMock

    from verboisy.core.planner import build_research_plan
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import Source, TaskSpec

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        },
    }

    runner = object.__new__(ResearchRunner)
    runner.rid = "run-1"
    runner.task = TaskSpec(target_records=5)
    runner.plan = build_research_plan(schema, 5)
    runner.store = MagicMock()
    runner.store.records.return_value = []

    sources = []

    for index in range(11):
        sources.extend(
            [
                Source(
                    id=f"name-{index}",
                    kind="text",
                    text=f"Country {index}",
                    scope=f"s{index}",
                ),
                Source(
                    id=f"value-{index}",
                    kind="text",
                    text=str(index),
                    scope=f"s{index}",
                ),
            ]
        )

    result = runner.window_batches([sources])

    assert len(result) == 2

    assert {source.id for batch in result for source in batch} == {source.id for source in sources}


@pytest.mark.asyncio
async def test_runner_semantic_plan_classifies_persists_and_reuses(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from verboisy.core.fitness import FieldSemantics
    from verboisy.core.planner import TemporalIntent
    from verboisy.core.research import ResearchRunner

    semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=0.95,
            basis="model",
        )
    }

    classify = AsyncMock(return_value=semantics)

    monkeypatch.setattr(
        "verboisy.core.research." "classify_field_semantics",
        classify,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = False
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.client = object()
    runner.goal = "Find latest population"
    runner.schema = {
        "type": "object",
        "properties": {
            "population": {
                "type": "integer",
            }
        },
    }
    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
        )
    }
    runner.temporal_intent = TemporalIntent(mode="latest")
    runner.current_year = 2026
    runner.rid = "run"
    runner.store = SimpleNamespace(event=MagicMock())
    runner.extractor = SimpleNamespace(
        field_semantics={},
        temporal_intent=None,
        current_year=None,
    )

    await runner.ensure_field_semantics()

    classify.assert_awaited_once_with(
        runner.client,
        goal="Find latest population",
        schema=runner.schema,
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert runner.semantic_plan_ready
    assert runner.field_semantics == semantics
    assert runner.extractor.field_semantics == semantics
    assert runner.extractor.temporal_intent == TemporalIntent(mode="latest")
    assert runner.extractor.current_year == 2026

    assert runner.store.event.call_args.args[0] == "run"
    assert runner.store.event.call_args.args[1] == "field_semantics_plan"

    payload = runner.store.event.call_args.args[2]

    assert payload["version"] == 1
    assert payload["research_year"] == 2026

    # A second call is free: no model call and
    # no duplicate persisted event.
    await runner.ensure_field_semantics()

    assert classify.await_count == 1
    assert runner.store.event.call_count == 1


def test_runner_restores_semantic_plan_on_resume(
    config,
):
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.semantic_planner import (
        semantic_plan_event,
    )
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import (
        ResearchStore,
    )

    schema = {
        "type": "object",
        "properties": {
            "population": {
                "type": "integer",
            }
        },
    }

    semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(
                mode="year",
                start_year=2025,
                end_year=2025,
            ),
            comparable_across_rows=True,
            confidence=0.93,
            basis="model",
        )
    }

    store = ResearchStore(config.sqlite_db_path)

    try:
        rid = store.create(
            "Find population in 2025",
            schema,
            TaskSpec(),
            None,
        )

        store.event(
            rid,
            "field_semantics_plan",
            semantic_plan_event(
                semantics,
                research_year=2025,
                temporal_intent=TemporalIntent(
                    mode="year",
                    start_year=2025,
                    end_year=2025,
                ),
            ),
        )

        runner = ResearchRunner(
            store,
            rid,
            config,
        )

        assert runner.semantic_plan_ready
        assert runner.current_year == 2025
        assert runner.temporal_intent == (
            TemporalIntent(
                mode="year",
                start_year=2025,
                end_year=2025,
            )
        )
        assert runner.field_semantics == semantics
        assert runner.extractor.field_semantics == semantics

    finally:
        store.close()


@pytest.mark.asyncio
async def test_ready_semantic_plan_skips_classifier(
    monkeypatch,
):
    from unittest.mock import AsyncMock

    from verboisy.core.research import ResearchRunner

    classify = AsyncMock()

    monkeypatch.setattr(
        "verboisy.core.research." "classify_field_semantics",
        classify,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = True

    await runner.ensure_field_semantics()

    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_semantic_planner_uses_baseline_without_persisting(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )

    classify = AsyncMock()

    monkeypatch.setattr(
        "verboisy.core.research." "classify_field_semantics",
        classify,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = False
    runner.field_semantics = {
        "/value": FieldSemantics(
            pointer="/value",
        )
    }
    runner.semantic_planning_available = MagicMock(return_value=False)
    runner.store = SimpleNamespace(event=MagicMock())

    await runner.ensure_field_semantics()

    assert runner.semantic_plan_ready
    classify.assert_not_awaited()
    runner.store.event.assert_not_called()


@pytest.mark.parametrize(
    ("model", "settings", "expected"),
    [
        (
            "gpt-4.1-mini",
            {},
            False,
        ),
        (
            "gpt-4.1-mini",
            {"openai_api_key": object()},
            True,
        ),
        (
            "anthropic/claude-sonnet",
            {},
            False,
        ),
        (
            "anthropic/claude-sonnet",
            {"anthropic_api_key": object()},
            True,
        ),
        (
            "custom/model",
            {"litellm_api_key": object()},
            True,
        ),
        (
            "custom/model",
            {"litellm_api_base": "http://local"},
            True,
        ),
        (
            "custom/model",
            {},
            True,
        ),
    ],
)
def test_semantic_planning_provider_detection(
    model,
    settings,
    expected,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.config = SimpleNamespace(**settings)
    runner.client = SimpleNamespace(model=model)

    assert runner.semantic_planning_available() is expected


def test_semantic_planning_requires_runner_state():
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.config = None
    runner.client = SimpleNamespace(model="gpt-4.1-mini")

    assert not runner.semantic_planning_available()

    runner.config = SimpleNamespace()
    runner.client = None

    assert not runner.semantic_planning_available()


@pytest.mark.asyncio
async def test_explicit_field_semantics_are_persisted_without_classification(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from verboisy.core.fitness import FieldSemantics
    from verboisy.core.planner import TemporalIntent
    from verboisy.core.research import ResearchRunner

    classify = AsyncMock()

    monkeypatch.setattr(
        "verboisy.core.research.classify_field_semantics",
        classify,
    )

    semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=1.0,
            basis="explicit",
        )
    }

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = False
    runner.field_semantics = semantics
    runner.temporal_intent = TemporalIntent(mode="latest")
    runner.current_year = 2026
    runner.rid = "run"
    runner.store = SimpleNamespace(event=MagicMock())
    runner.extractor = SimpleNamespace(
        field_semantics={},
        temporal_intent=None,
        current_year=None,
    )

    await runner.ensure_field_semantics()

    classify.assert_not_awaited()

    assert runner.semantic_plan_ready
    assert runner.field_semantics == semantics
    assert runner.extractor.field_semantics == semantics
    assert runner.store.event.call_count == 1
    assert runner.store.event.call_args.args[1] == "field_semantics_plan"


@pytest.mark.asyncio
async def test_invalid_semantic_plan_becomes_coverage_gap(
    config,
    world,
    monkeypatch,
):
    from unittest.mock import AsyncMock

    from verboisy.core.research import ResearchRunner
    from verboisy.extractor.evidenced import (
        EvidenceExtractor,
    )
    from verboisy.storage.research import ResearchStore
    from verboisy.utils.exceptions import (
        LLMResponseError,
    )

    ensure = AsyncMock(side_effect=LLMResponseError("invalid semantic plan"))
    propose = AsyncMock()

    monkeypatch.setattr(
        ResearchRunner,
        "ensure_field_semantics",
        ensure,
    )
    monkeypatch.setattr(
        EvidenceExtractor,
        "propose",
        propose,
    )

    result = await arun(
        goal="Find",
        schema=SCHEMA,
        task=task(),
        config=config,
    )

    assert not result.completed
    assert result.stop_reason == "coverage_or_identity_gaps"

    ensure.assert_awaited_once()
    propose.assert_not_awaited()

    store = ResearchStore(config.sqlite_db_path)

    try:
        gaps = [
            event["payload"]
            for event in store.events(
                result.run_id,
                "coverage_gap",
            )
        ]

        assert {"reason": "invalid_semantic_plan"} in gaps

    finally:
        store.close()


@pytest.mark.asyncio
async def test_failed_semantic_plan_rejects_direct_retry():
    from verboisy.core.research import ResearchRunner
    from verboisy.utils.exceptions import LLMResponseError

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = False
    runner.semantic_plan_failed = True

    with pytest.raises(
        LLMResponseError,
        match="semantic planning already failed",
    ):
        await runner.ensure_field_semantics()


@pytest.mark.asyncio
async def test_runner_supersedes_older_latest_fact(
    config,
    world,
    monkeypatch,
):
    from verboisy.core.fitness import FieldSemantics
    from verboisy.core.planner import TemporalIntent
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import (
        Candidate,
        PageProposal,
        TemporalProof,
    )
    from verboisy.extractor.evidenced import EvidenceExtractor
    from verboisy.storage.research import ResearchStore

    schema = {
        "type": "object",
        "properties": {
            "customer": {"type": "string"},
            "population": {"type": "integer"},
        },
        "required": [
            "customer",
            "population",
        ],
        "additionalProperties": False,
    }

    semantics = {
        "/customer": FieldSemantics(
            pointer="/customer",
            temporal_class="static",
            reference_period="none",
            confidence=1.0,
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=1.0,
            basis="model",
        ),
    }

    async def ensure_semantics(self):
        self.field_semantics = semantics
        self.semantic_plan_ready = True
        self.extractor.field_semantics = semantics

    async def propose(self, page, sources):
        if page.url.endswith("/a"):
            population = 100
            year = 2022
        else:
            population = 110
            year = 2025

        return PageProposal(
            candidates=[
                Candidate(
                    scope="page",
                    record={
                        "customer": "same-id",
                        "population": population,
                    },
                    evidence={},
                    temporal_evidence={
                        "/population": TemporalProof(
                            source="e1",
                            quote=str(year),
                            reference_year=year,
                        )
                    },
                )
            ],
            priority_links=[],
        )

    async def check(
        self,
        candidate,
        page,
    ):
        return []

    monkeypatch.setattr(
        ResearchRunner,
        "ensure_field_semantics",
        ensure_semantics,
    )
    monkeypatch.setattr(
        EvidenceExtractor,
        "propose",
        propose,
    )
    monkeypatch.setattr(
        EvidenceExtractor,
        "check",
        check,
    )

    result = await arun(
        goal="Find latest population",
        schema=schema,
        task=task(
            seed_urls=[
                "https://people.test/a",
                "https://people.test/b",
            ],
            allowed_hosts=["people.test"],
            target_records=2,
            identity_fields=["/customer"],
            max_depth=0,
            max_pages=2,
        ),
        config=config,
    )

    assert [{k: v for k, v in row.items() if k != "id"} for row in result.records] == [
        {
            "customer": "same-id",
            "population": 110,
        }
    ]

    assert result.records[0]["id"] == 1

    store = ResearchStore(config.sqlite_db_path)

    try:
        stored_rows = store.records(result.run_id)
        assert len(stored_rows) == 1
        internal_stable_id = stored_rows[0]["id"]

        assert store.summary(result.run_id)["identity_conflicts"] == 0

        superseded = store.events(
            result.run_id,
            "candidate_superseded",
        )

        assert len(superseded) == 1
        assert superseded[0]["payload"]["stable_id"] == internal_stable_id

        comparisons = store.events(
            result.run_id,
            "candidate_comparison",
        )

        assert any(event["payload"]["preference"] == "new" for event in comparisons)

    finally:
        store.close()


@pytest.mark.asyncio
async def test_source_assessment_cache_miss_then_hit(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="page",
        record={"value": "example"},
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    response = SourceAssessmentBatchResponse(
        candidates=[
            CandidateSourceAssessment(
                candidate_index=0,
                assessments=[],
            )
        ]
    )

    assess = AsyncMock(return_value=response)

    monkeypatch.setattr(
        "verboisy.core.research." "assess_source_batch",
        assess,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.goal = "Find value"
    runner.client = SimpleNamespace()
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.store = SimpleNamespace(
        events=MagicMock(return_value=[]),
        event=MagicMock(),
    )

    first = await runner.source_assess_candidates(
        page,
        [candidate],
    )
    second = await runner.source_assess_candidates(
        page,
        [candidate],
    )

    assert first
    assert second
    assess.assert_awaited_once()

    kinds = [call.args[1] for call in runner.store.event.call_args_list]

    assert kinds.count("source_assessment_cache") == 1
    assert kinds.count("source_fitness") == 2

    fitness_events = [
        call.args[2]
        for call in runner.store.event.call_args_list
        if call.args[1] == "source_fitness"
    ]

    assert fitness_events[0]["cache_hit"] is False
    assert fitness_events[1]["cache_hit"] is True


@pytest.mark.asyncio
async def test_source_assessment_unavailable_costs_nothing():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_planning_available = MagicMock(return_value=False)
    runner.store = SimpleNamespace(
        events=MagicMock(),
        event=MagicMock(),
    )

    result = await runner.source_assess_candidates(
        Snapshot(
            id="snapshot",
            url="https://example.test/",
            fetched_at=("2026-10-01T12:00:00+00:00"),
            content_hash="hash",
            sources=[],
            truncated=False,
        ),
        [
            Candidate(
                scope="page",
                record={"value": "x"},
                evidence={},
                temporal_evidence={},
            )
        ],
    )

    assert result == []
    runner.store.events.assert_not_called()
    runner.store.event.assert_not_called()


@pytest.mark.asyncio
async def test_source_assessment_failure_does_not_block_candidate(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )
    from verboisy.utils.exceptions import (
        LLMResponseError,
    )

    assess = AsyncMock(side_effect=LLMResponseError("invalid assessment"))

    monkeypatch.setattr(
        "verboisy.core.research." "assess_source_batch",
        assess,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.goal = "Find value"
    runner.client = SimpleNamespace()
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.store = SimpleNamespace(
        events=MagicMock(return_value=[]),
        event=MagicMock(),
    )

    result = await runner.source_assess_candidates(
        Snapshot(
            id="snapshot",
            url="https://example.test/",
            fetched_at=("2026-10-01T12:00:00+00:00"),
            content_hash="hash",
            sources=[],
            truncated=False,
        ),
        [
            Candidate(
                scope="page",
                record={"value": "x"},
                evidence={},
                temporal_evidence={},
            )
        ],
    )

    assert result == []

    runner.store.event.assert_called_once_with(
        "run",
        "source_assessment_skipped",
        {
            "url": "https://example.test/",
            "reason": ("assessment_call_failed"),
        },
    )


@pytest.mark.asyncio
async def test_invalid_source_grounding_is_observational_only(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    monkeypatch.setattr(
        "verboisy.core.research." "assess_source_batch",
        AsyncMock(
            return_value=(
                SourceAssessmentBatchResponse(
                    candidates=[CandidateSourceAssessment(candidate_index=0)]
                )
            )
        ),
    )

    monkeypatch.setattr(
        "verboisy.core.research." "ground_source_assessment_batch",
        MagicMock(side_effect=ValueError("invalid grounding")),
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.goal = "Find value"
    runner.client = SimpleNamespace()
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.store = SimpleNamespace(
        events=MagicMock(return_value=[]),
        event=MagicMock(),
    )

    result = await runner.source_assess_candidates(
        Snapshot(
            id="snapshot",
            url="https://example.test/",
            fetched_at=("2026-10-01T12:00:00+00:00"),
            content_hash="hash",
            sources=[],
            truncated=False,
        ),
        [
            Candidate(
                scope="page",
                record={"value": "x"},
                evidence={},
                temporal_evidence={},
            )
        ],
    )

    assert result == []

    kinds = [call.args[1] for call in runner.store.event.call_args_list]

    # Raw response is cached once so resume
    # never pays again for the same bad answer.
    assert kinds == [
        "source_assessment_cache",
        "source_assessment_skipped",
    ]


def test_accepted_candidate_context_without_identity_fields():
    from unittest.mock import MagicMock

    from verboisy.evidence.models import (
        Candidate,
        TaskSpec,
    )
    from verboisy.storage.research import (
        ResearchStore,
    )

    store = ResearchStore.__new__(ResearchStore)
    store.db = MagicMock()

    candidate = Candidate(
        scope="page",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    assert (
        store.accepted_candidate_context(
            "run",
            candidate,
            TaskSpec(),
        )
        is None
    )

    store.db.execute.assert_not_called()


def test_accepted_candidate_context_missing_record():
    from unittest.mock import MagicMock

    from verboisy.evidence.models import (
        Candidate,
        TaskSpec,
    )
    from verboisy.storage.research import (
        ResearchStore,
    )

    candidate = Candidate(
        scope="page",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    cursor = MagicMock()
    cursor.fetchone.return_value = None

    store = ResearchStore.__new__(ResearchStore)
    store.db = MagicMock()
    store.db.execute.return_value = cursor

    assert (
        store.accepted_candidate_context(
            "run",
            candidate,
            TaskSpec(identity_fields=["/name"]),
        )
        is None
    )

    store.db.execute.assert_called_once()


def test_accepted_candidate_context_returns_candidate_and_snapshot():
    from unittest.mock import MagicMock

    from verboisy.evidence.models import (
        Candidate,
        TaskSpec,
    )
    from verboisy.storage.research import (
        ResearchStore,
    )

    accepted = Candidate(
        scope="page",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
        temporal_evidence={},
    )

    newcomer = Candidate(
        scope="page",
        record={
            "name": "Example",
            "population": 110,
        },
        evidence={},
        temporal_evidence={},
    )

    from verboisy.evidence.snapshot import snapshot

    page = snapshot("<p>Example</p>", "https://example.test/")
    page = page.model_copy(update={"id": "snapshot-1"})
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "payload": (accepted.model_dump_json()),
        "snapshot_id": "snapshot-1",
        "run_id": "run",
        "accepted": 1,
        "snapshot_run_id": "run",
        "page_run_id": "run",
        "candidate_id": 1,
        "snapshot": page.model_dump_json(),
        "record_payload": json.dumps(accepted.record),
    }

    store = ResearchStore.__new__(ResearchStore)
    store.db = MagicMock()
    store.db.execute.return_value = cursor

    result = store.accepted_candidate_context(
        "run",
        newcomer,
        TaskSpec(identity_fields=["/name"]),
    )

    assert result is not None

    candidate_result, snapshot_id = result

    assert candidate_result == accepted
    assert snapshot_id == "snapshot-1"


def _runner_latest_candidate(
    value,
    year,
):
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    return Candidate(
        scope="page",
        record={
            "name": "Example",
            "population": value,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e1",
                quote=str(year),
                reference_year=year,
            )
        },
    )


def _runner_latest_semantics():
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )

    return {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            reference_period="none",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
        ),
    }


def _runner_claim_fitness(
    *,
    strong,
    year,
):
    from verboisy.core.fitness import (
        ClaimFitness,
    )

    if strong:
        return ClaimFitness(
            pointer="/population",
            authority="responsible",
            directness="primary",
            methodology="explicit",
            provenance="traceable",
            corroboration=1,
            reference_year=year,
        )

    return ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="partial",
        provenance="attributed",
        corroboration=0,
        reference_year=year,
    )


def test_runner_quality_aware_comparison_blocks_weaker_newer_source(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import verboisy.core.evidence_comparison as comparison_module
    from verboisy.core.research import (
        ResearchRunner,
    )

    old = _runner_latest_candidate(
        100,
        2024,
    )
    new = _runner_latest_candidate(
        110,
        2025,
    )

    decode = MagicMock(
        side_effect=[
            {
                "/population": (
                    _runner_claim_fitness(
                        strong=True,
                        year=2024,
                    )
                )
            },
            {
                "/population": (
                    _runner_claim_fitness(
                        strong=False,
                        year=2025,
                    )
                )
            },
        ]
    )

    monkeypatch.setattr(
        comparison_module,
        "source_fitness_from_events",
        decode,
    )

    events = MagicMock(
        return_value=[
            {
                "kind": "source_fitness",
                "payload": {},
            }
        ]
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace(events=events)

    comparison, mode = runner.compare_candidate_evidence(
        old,
        "old-snapshot",
        new,
        "new-snapshot",
    )

    assert mode == "source_fitness"
    assert comparison.temporal_preference == "new"
    assert comparison.preference == "old"

    events.assert_called_once_with(
        "run",
        "source_fitness",
    )

    assert decode.call_count == 2


def test_runner_quality_aware_comparison_allows_equal_quality_newer(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import verboisy.core.evidence_comparison as comparison_module
    from verboisy.core.research import (
        ResearchRunner,
    )

    old = _runner_latest_candidate(
        100,
        2024,
    )
    new = _runner_latest_candidate(
        110,
        2025,
    )

    decode = MagicMock(
        side_effect=[
            {
                "/population": (
                    _runner_claim_fitness(
                        strong=True,
                        year=2024,
                    )
                )
            },
            {
                "/population": (
                    _runner_claim_fitness(
                        strong=True,
                        year=2025,
                    )
                )
            },
        ]
    )

    monkeypatch.setattr(
        comparison_module,
        "source_fitness_from_events",
        decode,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace(events=MagicMock(return_value=[]))

    comparison, mode = runner.compare_candidate_evidence(
        old,
        "old-snapshot",
        new,
        "new-snapshot",
    )

    assert mode == "source_fitness"
    assert comparison.preference == "new"


def test_runner_comparison_falls_back_for_legacy_candidate():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )

    old = _runner_latest_candidate(
        100,
        2024,
    )
    new = _runner_latest_candidate(
        110,
        2025,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace(events=MagicMock(return_value=[]))

    comparison, mode = runner.compare_candidate_evidence(
        old,
        "old-snapshot",
        new,
        "new-snapshot",
    )

    assert mode == "temporal_fallback"
    assert comparison.preference == "new"


def test_runner_comparison_falls_back_without_snapshot_context():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )

    old = _runner_latest_candidate(
        100,
        2024,
    )
    new = _runner_latest_candidate(
        110,
        2025,
    )

    events = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace(events=events)

    comparison, mode = runner.compare_candidate_evidence(
        old,
        None,
        new,
        "new-snapshot",
    )

    assert mode == "temporal_fallback"
    assert comparison.preference == "new"
    events.assert_not_called()


def test_runner_comparison_falls_back_without_events_api():
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace()

    comparison, mode = runner.compare_candidate_evidence(
        _runner_latest_candidate(
            100,
            2024,
        ),
        "old-snapshot",
        _runner_latest_candidate(
            110,
            2025,
        ),
        "new-snapshot",
    )

    assert mode == "temporal_fallback"
    assert comparison.preference == "new"


def test_accepted_candidate_returns_none_when_identity_not_present():
    from unittest.mock import MagicMock

    from verboisy.evidence.models import (
        Candidate,
        TaskSpec,
    )
    from verboisy.storage.research import (
        ResearchStore,
    )

    candidate = Candidate(
        scope="page",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    cursor = MagicMock()
    cursor.fetchone.return_value = None

    store = ResearchStore.__new__(ResearchStore)
    store.db = MagicMock()
    store.db.execute.return_value = cursor

    result = store.accepted_candidate(
        "run",
        candidate,
        TaskSpec(identity_fields=["/name"]),
    )

    assert result is None
    store.db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_runner_uses_legacy_accepted_candidate_fallback(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    import verboisy.core.research as research
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
        Source,
    )

    candidate = Candidate(
        scope="page",
        record={
            "name": "Example",
        },
        evidence={},
        temporal_evidence={},
    )

    captured = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[
            Source(
                id="e1",
                kind="text",
                text="Example",
                scope="page",
            )
        ],
        truncated=False,
    )

    monkeypatch.setattr(
        research,
        "snapshot",
        lambda *_args, **_kwargs: captured,
    )

    monkeypatch.setattr(
        research,
        "chunks",
        lambda *_args, **_kwargs: [captured.sources],
    )

    browser_page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "oversized": False,
                "url": ("https://example.test/"),
                "html": ("<html>Example</html>"),
                "visible_html": ("<html>Example</html>"),
            }
        )
    )

    accepted_candidate = MagicMock(return_value=None)

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.task = SimpleNamespace(
        settle_ms=0,
        identity_fields=["/name"],
        pagination_selector=None,
    )
    runner.config = SimpleNamespace(
        max_page_bytes=100_000,
        max_snapshot_chars=100_000,
        max_dom_chars=10_000,
    )
    runner.adaptive_frontier = False

    runner.browser = SimpleNamespace(
        navigate_to=AsyncMock(),
        get_page=AsyncMock(return_value=browser_page),
    )

    runner.extractor = SimpleNamespace(
        propose=AsyncMock(
            return_value=SimpleNamespace(
                candidates=[candidate],
                priority_links=[],
            )
        ),
        check=AsyncMock(return_value=[]),
    )

    runner.ensure_field_semantics = AsyncMock()
    runner.source_assess_candidates = AsyncMock(return_value=[])

    runner.in_scope = MagicMock(return_value=True)
    runner.target_met = MagicMock(return_value=True)
    runner.record_source_productivity = MagicMock()
    runner.discover = MagicMock()

    # Deliberately no accepted_candidate_context:
    # this exercises compatibility with older/
    # lightweight store implementations.
    runner.store = SimpleNamespace(
        snapshot=MagicMock(),
        accepted_candidate=(accepted_candidate),
        accept=MagicMock(return_value="accepted"),
        event=MagicMock(),
        mark_page=MagicMock(),
    )

    await runner.process(
        {
            "id": 1,
            "url": ("https://example.test/"),
            "depth": 0,
        }
    )

    accepted_candidate.assert_called_once_with(
        "run",
        candidate,
        runner.task,
    )

    runner.store.accept.assert_called_once()


@pytest.mark.asyncio
async def test_runner_accepts_when_store_has_no_incumbent_lookup_api(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import verboisy.core.research as research
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
        Source,
    )

    candidate = Candidate(
        scope="page",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    captured = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T12:00:00+00:00",
        content_hash="hash",
        sources=[
            Source(
                id="e1",
                kind="text",
                text="Example",
                scope="page",
            )
        ],
        truncated=False,
    )

    monkeypatch.setattr(
        research,
        "snapshot",
        lambda *_args, **_kwargs: captured,
    )
    monkeypatch.setattr(
        research,
        "chunks",
        lambda *_args, **_kwargs: [captured.sources],
    )

    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "oversized": False,
                "url": captured.url,
                "html": "<html>Example</html>",
                "visible_html": ("<html>Example</html>"),
            }
        )
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.task = SimpleNamespace(
        settle_ms=0,
        identity_fields=["/name"],
        pagination_selector=None,
    )
    runner.config = SimpleNamespace(
        max_page_bytes=100_000,
        max_snapshot_chars=100_000,
        max_dom_chars=10_000,
    )
    runner.adaptive_frontier = False

    runner.browser = SimpleNamespace(
        navigate_to=AsyncMock(),
        get_page=AsyncMock(return_value=page),
    )
    runner.extractor = SimpleNamespace(
        propose=AsyncMock(
            return_value=SimpleNamespace(
                candidates=[candidate],
                priority_links=[],
            )
        ),
        check=AsyncMock(return_value=[]),
    )

    runner.ensure_field_semantics = AsyncMock()
    runner.source_assess_candidates = AsyncMock(return_value=[])
    runner.in_scope = MagicMock(return_value=True)
    runner.target_met = MagicMock(return_value=True)
    runner.record_source_productivity = MagicMock()
    runner.discover = MagicMock()

    # Deliberately exposes neither
    # accepted_candidate_context nor
    # accepted_candidate.
    runner.store = SimpleNamespace(
        snapshot=MagicMock(),
        accept=MagicMock(return_value="accepted"),
        event=MagicMock(),
        mark_page=MagicMock(),
    )

    await runner.process(
        {
            "id": 1,
            "url": captured.url,
            "depth": 0,
        }
    )

    runner.store.accept.assert_called_once_with(
        "run",
        captured,
        candidate,
        [],
        runner.task,
        preference=None,
    )


def test_runner_same_period_conflict_uses_persisted_corroboration():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.fitness import ClaimFitness
    from verboisy.core.provenance import provenance_identity
    from verboisy.core.research import ResearchRunner
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
        source_fitness_from_events,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
        Source,
        TemporalProof,
    )

    def candidate(
        population: int,
    ) -> Candidate:
        return Candidate(
            scope="entity",
            record={
                "name": "Example",
                "population": population,
            },
            evidence={},
            temporal_evidence={
                "/population": TemporalProof(
                    source="period",
                    quote="2025",
                    reference_year=2025,
                )
            },
        )

    def fitness_event(
        candidate: Candidate,
        *,
        snapshot_id: str,
        label: str,
        host: str,
    ) -> dict[str, object]:
        source = Source(
            id=f"source-{snapshot_id}",
            kind="link",
            text=f"Source: {label}",
            scope="page",
            href=f"https://{host}/data",
        )

        origin = provenance_identity(
            source,
            label=label,
            quote=f"Source: {label}",
        )

        assert origin is not None

        page = Snapshot(
            id=snapshot_id,
            url=(f"https://page-{snapshot_id}.example/"),
            fetched_at=("2026-10-01T12:00:00+00:00"),
            content_hash=f"hash-{snapshot_id}",
            sources=[source],
            truncated=False,
        )

        payload = source_fitness_event(
            page,
            candidate,
            {
                "/population": (
                    GroundedClaimAssessment(
                        pointer="/population",
                        fitness=ClaimFitness(
                            pointer="/population",
                            authority="general",
                            reference_year=2025,
                        ),
                        grounded=True,
                        reason=None,
                        citation_sources=(source.id,),
                        provenance_identity=origin,
                    )
                )
            },
            cache_key=f"cache-{snapshot_id}",
            cache_hit=False,
            identity_fields=("/name",),
        )

        return {
            "kind": "source_fitness",
            "payload": payload,
        }

    old = candidate(100)
    new = candidate(101)

    events = [
        # First independent origin supporting
        # the incumbent value.
        fitness_event(
            old,
            snapshot_id="old-support",
            label="Agency A",
            host="agency-a.example",
        ),
        # Incumbent's own persisted source.
        fitness_event(
            old,
            snapshot_id="old-snapshot",
            label="Agency B",
            host="agency-b.example",
        ),
        # One origin supports the conflicting value.
        fitness_event(
            new,
            snapshot_id="new-snapshot",
            label="Agency C",
            host="agency-c.example",
        ),
    ]

    old_fitness = source_fitness_from_events(
        events,
        snapshot_id="old-snapshot",
        candidate=old,
        field_semantics=_runner_latest_semantics(),
    )
    new_fitness = source_fitness_from_events(
        events,
        snapshot_id="new-snapshot",
        candidate=new,
        field_semantics=_runner_latest_semantics(),
    )

    assert old_fitness is not None
    assert new_fitness is not None

    assert old_fitness["/population"].corroboration == 1
    assert new_fitness["/population"].corroboration == 0

    stored_events = MagicMock(return_value=events)

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _runner_latest_semantics()
    runner.store = SimpleNamespace(events=stored_events)

    comparison, mode = runner.compare_candidate_evidence(
        old,
        "old-snapshot",
        new,
        "new-snapshot",
    )

    assert mode == "source_fitness"

    # Same reference period + different value.
    assert comparison.temporal_preference == "conflict"

    # The incumbent has two independent origins;
    # the challenger has one.
    assert comparison.source_preferences["/population"] == "old"

    assert comparison.preference == "old"

    stored_events.assert_called_once_with(
        "run",
        "source_fitness",
    )


def test_runner_persists_model_escalation_event():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run-1"
    runner.store = SimpleNamespace(event=MagicMock())

    payload = {
        "role": "extraction",
        "reason": "validation_error",
        "primary_model": "cheap-model",
        "escalation_model": "strong-model",
    }

    runner.record_model_escalation(payload)

    runner.store.event.assert_called_once_with(
        "run-1",
        "model_escalation",
        payload,
    )


def test_target_met_requires_dataset_consistency():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        TaskSpec,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.task = TaskSpec(
        target_records=1,
    )
    runner.schema = {
        "type": "object",
    }

    runner.store = SimpleNamespace(
        records=MagicMock(
            return_value=[
                {
                    "id": "row-1",
                    "value": 10,
                }
            ]
        ),
        summary=MagicMock(
            return_value={
                "identity_conflicts": 0,
            }
        ),
    )

    runner.dataset_consistency_gaps = MagicMock(return_value=("/value:mixed_reference_periods",))

    assert not runner.target_met()

    runner.dataset_consistency_gaps.return_value = ()

    assert runner.target_met()


def test_dataset_consistency_gaps_supports_legacy_store():
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.store = SimpleNamespace()

    assert runner.dataset_consistency_gaps() == ()


def test_runner_decodes_accepted_candidates_for_consistency():
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    def candidate(
        name,
        year,
    ):
        return Candidate(
            scope="entity",
            record={
                "name": name,
                "population": 100,
            },
            evidence={},
            temporal_evidence={
                "/population": TemporalProof(
                    source="period",
                    quote=str(year),
                    reference_year=year,
                )
            },
        )

    first = candidate(
        "A",
        2024,
    )
    second = candidate(
        "B",
        2025,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            comparable_across_rows=True,
            confidence=1.0,
            basis="model",
        )
    }

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {"candidate": (first.model_dump(mode="json"))},
            {"candidate": (second.model_dump(mode="json"))},
        ]
    )

    assert runner.dataset_consistency_gaps() == ("/population:mixed_reference_periods",)


@pytest.mark.asyncio
async def test_exhausted_frontier_reports_dataset_consistency_gap():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        return_value=False,
    )
    runner.source_scores = MagicMock(
        return_value={},
    )
    runner.dataset_consistency_gaps = MagicMock(
        return_value=("/population:mixed_reference_periods",)
    )

    event = MagicMock()

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "1"},
                {"id": "2"},
            ]
        ),
        summary=MagicMock(
            return_value={
                "pages": {
                    "failed": 1,
                },
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value=None,
        ),
        event=event,
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "PAUSED",
        "dataset_consistency_gaps",
    )

    event.assert_called_once_with(
        "run",
        "dataset_consistency_gap",
        {
            "gaps": ["/population:" "mixed_reference_periods"],
            "records": 2,
            "target_records": 2,
        },
    )

    runner.dataset_consistency_gaps.assert_called_once_with()


@pytest.mark.asyncio
async def test_incomplete_target_does_not_report_dataset_consistency_gap():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        return_value=False,
    )
    runner.source_scores = MagicMock(
        return_value={},
    )
    runner.dataset_consistency_gaps = MagicMock(
        return_value=("/population:mixed_reference_periods",)
    )

    event = MagicMock()

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "1"},
            ]
        ),
        summary=MagicMock(
            return_value={
                "pages": {},
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value=None,
        ),
        event=event,
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "EXHAUSTED",
        "observed_scope_exhausted",
    )

    runner.dataset_consistency_gaps.assert_not_called()
    event.assert_not_called()


@pytest.mark.asyncio
async def test_consistent_target_preserves_existing_source_failure_status():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        return_value=False,
    )
    runner.source_scores = MagicMock(
        return_value={},
    )
    runner.dataset_consistency_gaps = MagicMock(
        return_value=(),
    )

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "1"},
                {"id": "2"},
            ]
        ),
        summary=MagicMock(
            return_value={
                "pages": {
                    "failed": 1,
                },
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value=None,
        ),
        event=MagicMock(),
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "FAILED",
        "source_failures",
    )


def test_runner_maps_dataset_repairs_to_record_ids():
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    def candidate(
        year,
    ):
        return Candidate(
            scope="entity",
            record={
                "population": 100,
            },
            evidence={},
            temporal_evidence={
                "/population": TemporalProof(
                    source="period",
                    quote=str(year),
                    reference_year=year,
                )
            },
        )

    old = candidate(2024)
    current = candidate(2025)

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(
                mode="latest",
            ),
            comparable_across_rows=True,
            confidence=1.0,
            basis="model",
        )
    }

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "record_id": "row-old",
                "candidate": old.model_dump(mode="json"),
            },
            {
                "record_id": "row-current",
                "candidate": current.model_dump(mode="json"),
            },
        ]
    )

    repairs = runner.dataset_consistency_repairs()

    assert len(repairs) == 1

    assert repairs[0] == {
        "record_id": "row-old",
        "candidate_index": 0,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }


@pytest.mark.asyncio
async def test_dataset_consistency_diagnostic_includes_repairs():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        return_value=False,
    )
    runner.source_scores = MagicMock(
        return_value={},
    )
    runner.dataset_consistency_gaps = MagicMock(
        return_value=("/population:mixed_reference_periods",)
    )

    repair = {
        "record_id": "row-old",
        "candidate_index": 0,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }

    runner.dataset_consistency_repairs = MagicMock(return_value=(repair,))

    event = MagicMock()

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "row-old"},
                {"id": "row-current"},
            ]
        ),
        summary=MagicMock(
            return_value={
                "pages": {},
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value=None,
        ),
        event=event,
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "PAUSED",
        "dataset_consistency_gaps",
    )

    event.assert_called_once_with(
        "run",
        "dataset_consistency_gap",
        {
            "gaps": ["/population:" "mixed_reference_periods"],
            "records": 2,
            "target_records": 2,
            "repairs": [
                repair,
            ],
        },
    )

    runner.dataset_consistency_repairs.assert_called_once_with()


@pytest.mark.asyncio
async def test_dataset_repair_discovery_queues_scoped_sources(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
        call,
    )

    import verboisy.core.research as research
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.search import (
        SearchObservation,
        SearchResult,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    search = AsyncMock(
        return_value=SearchObservation(
            provider="openai",
            query="ignored",
            results=[
                SearchResult(
                    title="Blocked",
                    url=("https://blocked.example/" "population"),
                ),
                SearchResult(
                    title="Current",
                    url=("https://allowed.example/" "current"),
                ),
                SearchResult(
                    title="Official",
                    url=("https://allowed.example/" "official"),
                ),
            ],
        )
    )

    monkeypatch.setattr(
        research,
        "web_search",
        search,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
    )

    events = MagicMock(
        return_value=[],
    )
    event = MagicMock()
    queue = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.client = MagicMock()

    runner.rid = "run"
    runner.config = SimpleNamespace()

    runner.task = SimpleNamespace(
        identity_fields=[
            "/name",
        ],
        include_paths=[],
        exclude_paths=[],
    )

    runner.hosts = {
        "allowed.example",
    }
    runner.avoided_hosts = set()

    runner.store = SimpleNamespace(
        events=events,
        event=event,
        queue=queue,
        evidence=MagicMock(
            return_value=[
                {
                    "record_id": "row-old",
                    "candidate": (candidate.model_dump(mode="json")),
                }
            ]
        ),
    )

    repair = {
        "record_id": "row-old",
        "candidate_index": 0,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }

    queued = await runner.discover_dataset_repair_source((repair,))

    assert queued

    search.assert_awaited_once_with(
        "Example population 2025",
        runner.config,
    )

    assert queue.call_args_list == [
        call(
            "run",
            "https://allowed.example/current",
            0,
            None,
        ),
        call(
            "run",
            "https://allowed.example/official",
            0,
            None,
        ),
    ]

    event.assert_called_once()

    args = event.call_args.args

    assert args[0] == "run"
    assert args[1] == ("dataset_repair_discovery")

    payload = args[2]

    assert payload["record_id"] == "row-old"
    assert payload["pointer"] == "/population"
    assert payload["target_year"] == 2025
    assert payload["query"] == ("Example population 2025")
    assert payload["provider"] == "openai"
    assert payload["status"] == "queued"
    assert payload["queued"] == [
        "https://allowed.example/current",
        "https://allowed.example/official",
    ]

    # The persisted fingerprint prevents the same
    # repair query from being paid for again.
    events.return_value = [
        {
            "payload": payload,
        }
    ]

    search.reset_mock()
    queue.reset_mock()
    event.reset_mock()

    queued_again = await runner.discover_dataset_repair_source((repair,))

    assert not queued_again
    search.assert_not_awaited()
    queue.assert_not_called()
    event.assert_not_called()


@pytest.mark.asyncio
async def test_dataset_repair_discovery_persists_search_unavailable(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    import verboisy.core.research as research
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )
    from verboisy.utils.exceptions import (
        SearchUnavailableError,
    )

    search = AsyncMock(side_effect=SearchUnavailableError("search unavailable"))

    monkeypatch.setattr(
        research,
        "web_search",
        search,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
    )

    event = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.client = MagicMock()
    runner.rid = "run"
    runner.config = SimpleNamespace()

    runner.task = SimpleNamespace(
        identity_fields=["/name"],
        include_paths=[],
        exclude_paths=[],
    )

    runner.hosts = set()
    runner.avoided_hosts = set()

    runner.store = SimpleNamespace(
        events=MagicMock(
            return_value=[],
        ),
        event=event,
        queue=MagicMock(),
        evidence=MagicMock(
            return_value=[
                {
                    "record_id": "row-old",
                    "candidate": (candidate.model_dump(mode="json")),
                }
            ]
        ),
    )

    result = await runner.discover_dataset_repair_source(
        (
            {
                "record_id": "row-old",
                "candidate_index": 0,
                "pointer": "/population",
                "reason": ("stale_reference_period"),
                "observed_year": 2024,
                "target_year": 2025,
                "target_mode": "latest",
            },
        )
    )

    assert not result

    payload = event.call_args.args[2]

    assert payload["status"] == "unavailable"
    assert payload["queued"] == []
    assert payload["error"] == ("search unavailable")


@pytest.mark.asyncio
async def test_dataset_repair_discovery_persists_empty_scoped_results(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    import verboisy.core.research as research
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.search import (
        SearchObservation,
        SearchResult,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    monkeypatch.setattr(
        research,
        "web_search",
        AsyncMock(
            return_value=SearchObservation(
                provider="openai",
                query="ignored",
                results=[
                    SearchResult(
                        title="Outside scope",
                        url=("https://blocked.example/" "population"),
                    )
                ],
            )
        ),
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
    )

    event = MagicMock()
    queue = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.client = MagicMock()
    runner.rid = "run"
    runner.config = SimpleNamespace()

    runner.task = SimpleNamespace(
        identity_fields=["/name"],
        include_paths=[],
        exclude_paths=[],
    )

    runner.hosts = {
        "allowed.example",
    }
    runner.avoided_hosts = set()

    runner.store = SimpleNamespace(
        events=MagicMock(
            return_value=[],
        ),
        event=event,
        queue=queue,
        evidence=MagicMock(
            return_value=[
                {
                    "record_id": "row-old",
                    "candidate": (candidate.model_dump(mode="json")),
                }
            ]
        ),
    )

    result = await runner.discover_dataset_repair_source(
        (
            {
                "record_id": "row-old",
                "candidate_index": 0,
                "pointer": "/population",
                "reason": ("stale_reference_period"),
                "observed_year": 2024,
                "target_year": 2025,
                "target_mode": "latest",
            },
        )
    )

    assert not result
    queue.assert_not_called()

    payload = event.call_args.args[2]

    assert payload["status"] == "empty"
    assert payload["queued"] == []


@pytest.mark.asyncio
async def test_run_attempts_targeted_repair_before_frontier_work():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import (
        ResearchRunner,
    )

    repair = {
        "record_id": "row-old",
        "candidate_index": 0,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        identity_fields=["/name"],
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        side_effect=[
            False,
            True,
        ],
    )

    runner.dataset_consistency_repairs = MagicMock(return_value=(repair,))

    runner.discover_dataset_repair_source = AsyncMock(
        return_value=True,
    )

    runner.source_scores = MagicMock(
        return_value={},
    )

    runner.process = AsyncMock()

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "row-old"},
                {"id": "row-current"},
            ]
        ),
        evidence=MagicMock(),
        events=MagicMock(),
        event=MagicMock(),
        queue=MagicMock(),
        summary=MagicMock(
            return_value={
                "pages": {},
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value={
                "id": 7,
                "url": ("https://example.test/" "repair"),
                "depth": 0,
            }
        ),
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "COMPLETED",
        "target_met",
    )

    runner.discover_dataset_repair_source.assert_awaited_once_with((repair,))

    runner.process.assert_awaited_once()


def test_dataset_repair_discovery_requires_durable_store_and_identity():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"

    runner.task = SimpleNamespace(
        identity_fields=[],
        target_records=2,
    )

    runner.store = SimpleNamespace()

    assert not (runner.dataset_repair_discovery_available())

    assert not runner.target_record_count_met()

    runner.task.identity_fields = ["/name"]

    runner.store = SimpleNamespace(
        records=MagicMock(
            return_value=[
                {"id": "1"},
                {"id": "2"},
            ]
        ),
        evidence=MagicMock(),
        events=MagicMock(),
        event=MagicMock(),
        queue=MagicMock(),
    )

    assert runner.dataset_repair_discovery_available()
    assert runner.target_record_count_met()


@pytest.mark.asyncio
async def test_dataset_repair_discovery_requires_identity_fields():
    from types import SimpleNamespace

    from verboisy.core.research import ResearchRunner

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.task = SimpleNamespace(
        identity_fields=[],
    )

    result = await runner.discover_dataset_repair_source(())

    assert not result


@pytest.mark.asyncio
async def test_dataset_repair_discovery_ignores_malformed_attempt_events():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import ResearchRunner

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.task = SimpleNamespace(
        identity_fields=["/name"],
    )

    runner.store = SimpleNamespace(
        events=MagicMock(
            return_value=[
                {
                    "payload": "not-a-dict",
                },
                {
                    "payload": {
                        "key": 123,
                    },
                },
            ]
        ),
        evidence=MagicMock(return_value=[]),
    )

    result = await runner.discover_dataset_repair_source(())

    assert not result

    runner.store.events.assert_called_once_with(
        "run",
        "dataset_repair_discovery",
    )
    runner.store.evidence.assert_called_once_with("run")


@pytest.mark.asyncio
async def test_dataset_repair_discovery_limits_queued_sources_to_three(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
        call,
    )

    import verboisy.core.research as research
    from verboisy.core.research import ResearchRunner
    from verboisy.core.search import (
        SearchObservation,
        SearchResult,
    )
    from verboisy.evidence.models import Candidate

    monkeypatch.setattr(
        research,
        "web_search",
        AsyncMock(
            return_value=SearchObservation(
                provider="openai",
                query="ignored",
                results=[
                    SearchResult(
                        title="One",
                        url="https://example.test/one",
                    ),
                    SearchResult(
                        title="Two",
                        url="https://example.test/two",
                    ),
                    SearchResult(
                        title="Three",
                        url="https://example.test/three",
                    ),
                    SearchResult(
                        title="Four",
                        url="https://example.test/four",
                    ),
                ],
            )
        ),
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
    )

    queue = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.client = MagicMock()
    runner.rid = "run"
    runner.config = SimpleNamespace()

    runner.task = SimpleNamespace(
        identity_fields=["/name"],
        include_paths=[],
        exclude_paths=[],
    )

    runner.hosts = set()
    runner.avoided_hosts = set()

    runner.store = SimpleNamespace(
        events=MagicMock(return_value=[]),
        evidence=MagicMock(
            return_value=[
                {
                    "record_id": "row-old",
                    "candidate": (candidate.model_dump(mode="json")),
                }
            ]
        ),
        queue=queue,
        event=MagicMock(),
    )

    repair = {
        "record_id": "row-old",
        "candidate_index": 0,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }

    result = await runner.discover_dataset_repair_source((repair,))

    assert result

    assert queue.call_args_list == [
        call(
            "run",
            "https://example.test/one",
            0,
            None,
        ),
        call(
            "run",
            "https://example.test/two",
            0,
            None,
        ),
        call(
            "run",
            "https://example.test/three",
            0,
            None,
        ),
    ]


@pytest.mark.asyncio
async def test_run_skips_repair_discovery_when_no_repairs_exist():
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    from verboisy.core.research import ResearchRunner

    runner = ResearchRunner.__new__(ResearchRunner)

    runner.rid = "run"
    runner.adaptive_frontier = False

    runner.task = SimpleNamespace(
        target_records=2,
        max_pages=100,
        max_depth=3,
    )

    runner.config = SimpleNamespace(
        run_timeout_seconds=10,
        action_delay_seconds=0,
    )

    runner.client = SimpleNamespace(
        total_tokens=0,
        reserved_tokens=0,
    )

    runner.browser = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
    )

    runner.target_met = MagicMock(
        return_value=False,
    )

    runner.dataset_repair_discovery_available = MagicMock(
        return_value=True,
    )

    runner.target_record_count_met = MagicMock(
        return_value=True,
    )

    runner.dataset_consistency_repairs = MagicMock(
        return_value=(),
    )

    runner.discover_dataset_repair_source = AsyncMock()

    runner.dataset_consistency_gaps = MagicMock(
        return_value=(),
    )

    runner.source_scores = MagicMock(
        return_value={},
    )

    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(
            return_value=[
                {"id": "1"},
                {"id": "2"},
            ]
        ),
        summary=MagicMock(
            return_value={
                "pages": {},
                "coverage_gaps": 0,
                "identity_conflicts": 0,
            }
        ),
        next_page=MagicMock(
            return_value=None,
        ),
        finish=MagicMock(),
    )

    status, reason = await runner.run(
        max_steps=1,
    )

    assert (status, reason) == (
        "EXHAUSTED",
        "observed_scope_exhausted",
    )

    runner.dataset_consistency_repairs.assert_called_once_with()
    runner.discover_dataset_repair_source.assert_not_awaited()


def test_repair_frontier_outranks_productive_generic_page(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(tmp_path / "repair-priority.sqlite3")

    try:
        rid = store.create(
            "Find",
            {
                "type": "object",
            },
            TaskSpec(),
            None,
        )

        store.queue(
            rid,
            "https://productive.test/data",
            0,
            None,
        )

        store.queue_repair(
            rid,
            "https://repair.test/data",
            0,
            None,
        )

        work = store.next_page(
            rid,
            {
                "productive.test": 1.0,
                "repair.test": -1.0,
            },
        )

        assert work is not None
        assert work["url"] == ("https://repair.test/data")

    finally:
        store.close()


def test_frontier_rebalance_does_not_demote_repair_work(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(tmp_path / "repair-rebalance.sqlite3")

    try:
        rid = store.create(
            "Find",
            {
                "type": "object",
            },
            TaskSpec(),
            None,
        )

        store.queue(
            rid,
            "https://generic.test/one",
            0,
            None,
        )
        store.queue(
            rid,
            "https://generic.test/two",
            0,
            None,
        )
        store.queue_repair(
            rid,
            "https://repair.test/current",
            0,
            None,
        )

        result = store.rebalance_frontier(
            rid,
            1,
        )

        assert result == {
            "queued": 1,
            "demoted": 1,
        }

        work = store.next_page(
            rid,
            {
                "generic.test": 1.0,
                "repair.test": -1.0,
            },
        )

        assert work is not None
        assert work["url"] == ("https://repair.test/current")

    finally:
        store.close()


def test_recover_restores_active_repair_priority(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(tmp_path / "repair-recover.sqlite3")

    try:
        rid = store.create(
            "Find",
            {
                "type": "object",
            },
            TaskSpec(),
            None,
        )

        repair_url = "https://repair.test/current"

        store.queue_repair(
            rid,
            repair_url,
            0,
            None,
        )

        first = store.next_page(
            rid,
        )

        assert first is not None
        assert first["url"] == repair_url

        # Simulate interruption while the repair page
        # is active.
        store.recover(rid)

        second = store.next_page(
            rid,
        )

        assert second is not None
        assert second["url"] == repair_url

    finally:
        store.close()


@pytest.mark.asyncio
async def test_dataset_repair_discovery_uses_repair_queue_when_available(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import (
        AsyncMock,
        MagicMock,
    )

    import verboisy.core.research as research
    from verboisy.core.research import ResearchRunner
    from verboisy.core.search import (
        SearchObservation,
        SearchResult,
    )
    from verboisy.evidence.models import Candidate

    monkeypatch.setattr(
        research,
        "web_search",
        AsyncMock(
            return_value=SearchObservation(
                provider="openai",
                query="ignored",
                results=[
                    SearchResult(
                        title="Current",
                        url=("https://example.test/current"),
                    )
                ],
            )
        ),
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
    )

    queue = MagicMock()
    queue_repair = MagicMock()

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.client = MagicMock()

    runner.rid = "run"
    runner.config = SimpleNamespace()

    runner.task = SimpleNamespace(
        identity_fields=[
            "/name",
        ],
        include_paths=[],
        exclude_paths=[],
    )

    runner.hosts = set()
    runner.avoided_hosts = set()

    runner.store = SimpleNamespace(
        events=MagicMock(
            return_value=[],
        ),
        evidence=MagicMock(
            return_value=[
                {
                    "record_id": "row-old",
                    "candidate": (candidate.model_dump(mode="json")),
                }
            ]
        ),
        event=MagicMock(),
        queue=queue,
        queue_repair=queue_repair,
    )

    result = await runner.discover_dataset_repair_source(
        (
            {
                "record_id": "row-old",
                "candidate_index": 0,
                "pointer": "/population",
                "reason": ("stale_reference_period"),
                "observed_year": 2024,
                "target_year": 2025,
                "target_mode": "latest",
            },
        )
    )

    assert result

    queue_repair.assert_called_once_with(
        "run",
        "https://example.test/current",
        0,
        None,
    )
    queue.assert_not_called()


def test_runner_exposes_grounded_accepted_comparability():
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        GroundedClaimComparability,
        GroundedComparabilityDescriptor,
        source_fitness_event,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
        Source,
    )

    source = Source(
        id="metadata",
        kind="link",
        text=("Population unit: " "thousands of persons."),
        scope="entity",
        href="https://example.test/meta",
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[
            source,
        ],
        truncated=False,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
        temporal_evidence={},
    )

    claims = {
        "/population": (
            GroundedClaimAssessment(
                pointer="/population",
                fitness=ClaimFitness(
                    pointer="/population",
                ),
                grounded=True,
                reason=None,
                citation_sources=("metadata",),
                comparability=(
                    GroundedClaimComparability(
                        unit=(
                            GroundedComparabilityDescriptor(
                                label=("thousands of persons"),
                                source="metadata",
                                quote=("Population unit: " "thousands of persons."),
                            )
                        )
                    )
                ),
            )
        )
    }

    event = source_fitness_event(
        snapshot,
        candidate,
        claims,
        cache_key="cache",
        cache_hit=False,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": (candidate.model_dump(mode="json")),
                "snapshot": (snapshot.model_dump(mode="json")),
            }
        ],
        events=lambda _rid, _kind: [
            {
                "payload": event,
            }
        ],
    )

    assert runner.dataset_comparability_observations() == (
        {
            "record_id": "row-1",
            "pointer": "/population",
            "unit": {
                "label": ("thousands of persons"),
                "source": "metadata",
                "quote": ("Population unit: " "thousands of persons."),
            },
            "observed_canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
        },
    )


def test_dataset_comparability_supports_legacy_store():
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.store = SimpleNamespace()

    assert runner.dataset_comparability_observations() == ()


def test_runner_skips_empty_comparability_observation(
    monkeypatch,
):
    from types import SimpleNamespace

    import verboisy.core.dataset_consistency as inspection
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimComparability,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "value": 1,
        },
        evidence={},
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    monkeypatch.setattr(
        inspection,
        "claim_comparability_from_events",
        lambda *_args, **_kwargs: {"/value": (GroundedClaimComparability())},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.store = SimpleNamespace(
        events=lambda _rid, _kind: [],
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": (candidate.model_dump(mode="json")),
                "snapshot": (snapshot.model_dump(mode="json")),
            }
        ],
    )

    assert runner.dataset_comparability_observations() == ()


def test_runner_canonicalizes_grounded_unit_synonym(
    monkeypatch,
):
    from types import SimpleNamespace

    import verboisy.core.dataset_consistency as inspection
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimComparability,
        GroundedComparabilityDescriptor,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "population": 100,
        },
        evidence={},
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    monkeypatch.setattr(
        inspection,
        "claim_comparability_from_events",
        lambda *_args, **_kwargs: {
            "/population": (
                GroundedClaimComparability(
                    unit=(
                        GroundedComparabilityDescriptor(
                            label="People",
                            source="metadata",
                            quote="People",
                        )
                    )
                )
            )
        },
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.store = SimpleNamespace(
        events=lambda _rid, _kind: [],
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": (candidate.model_dump(mode="json")),
                "snapshot": (snapshot.model_dump(mode="json")),
            }
        ],
    )

    observation = runner.dataset_comparability_observations()[0]

    assert observation["canonical_unit"] == {
        "dimension": "count",
        "base_unit": "person",
        "multiplier": 1,
    }


@pytest.mark.parametrize(
    "payload",
    [
        # 344 -> 353:
        # no unit descriptor at all.
        {
            "definition": {
                "label": "some definition",
                "source": "metadata",
                "quote": "some definition",
            }
        },
        # 347 -> 353:
        # unit exists, but its label is malformed.
        {
            "unit": {
                "label": 123,
                "source": "metadata",
                "quote": "123",
            }
        },
        # 350 -> 353:
        # valid literal label, but deterministic
        # canonicalizer does not recognize it.
        {
            "unit": {
                "label": "widgets",
                "source": "metadata",
                "quote": "widgets",
            }
        },
    ],
)
def test_runner_leaves_uncanonicalizable_comparability_unchanged(
    monkeypatch,
    payload,
):
    from types import SimpleNamespace

    import verboisy.core.dataset_consistency as inspection
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "value": 1,
        },
        evidence={},
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    comparability = SimpleNamespace(
        as_event=lambda: payload,
    )

    monkeypatch.setattr(
        inspection,
        "claim_comparability_from_events",
        lambda *_args, **_kwargs: {
            "/value": comparability,
        },
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.store = SimpleNamespace(
        events=lambda _rid, _kind: [],
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": (candidate.model_dump(mode="json")),
                "snapshot": (snapshot.model_dump(mode="json")),
            }
        ],
    )

    observations = runner.dataset_comparability_observations()

    assert len(observations) == 1

    observation = observations[0]

    assert observation["record_id"] == "row-1"
    assert observation["pointer"] == "/value"
    assert "canonical_unit" not in observation


def test_dataset_consistency_includes_unit_scale_gap(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"

    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="static",
            unit_sensitive=True,
            comparable_across_rows=True,
            confidence=1.0,
            basis="deterministic",
        )
    }

    candidate = Candidate(
        scope="entity",
        record={
            "population": 100,
        },
        evidence={},
    )

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "candidate": (candidate.model_dump(mode="json")),
            }
        ]
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        lambda: (
            {
                "record_id": "row-1",
                "pointer": "/population",
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
            },
            {
                "record_id": "row-2",
                "pointer": "/population",
                "observed_canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
            },
        ),
    )

    assert runner.dataset_consistency_gaps() == ("/population:mixed_unit_scales",)


def test_dataset_consistency_unit_checks_support_legacy_store():
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = {}
    runner.store = SimpleNamespace()

    assert runner.dataset_consistency_gaps() == ()


def test_runner_persists_scaled_unit_normalization(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    events = []

    candidate_a = Candidate(
        scope="entity",
        record={"population": 100},
        evidence={},
    )
    candidate_b = Candidate(
        scope="entity",
        record={"population": 2},
        evidence={},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="static",
            unit_sensitive=True,
            comparable_across_rows=True,
            confidence=1.0,
            basis="deterministic",
        )
    }

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-1",
                "candidate": candidate_a.model_dump(mode="json"),
            },
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-2",
                "candidate": candidate_b.model_dump(mode="json"),
            },
        ],
        events=lambda _rid, kind: (events if kind == "unit_normalization" else []),
        event=lambda _rid, _kind, payload: (
            events.append(
                {
                    "payload": payload,
                }
            )
        ),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        lambda: (
            {
                "record_id": "row-1",
                "pointer": "/population",
                "unit": {
                    "label": "persons",
                },
                "observed_canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
            },
            {
                "record_id": "row-2",
                "pointer": "/population",
                "unit": {
                    "label": "thousands of persons",
                },
                "observed_canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
            },
        ),
    )

    assert runner.ensure_unit_normalizations() == 1

    payload = events[0]["payload"]

    assert payload["record_id"] == "row-2"
    assert payload["pointer"] == "/population"
    assert payload["original_value"] == 2
    assert payload["normalized_value"] == 2_000
    assert payload["multiplier"] == 1_000


def test_runner_unit_normalization_is_idempotent(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.units import (
        CanonicalUnit,
        unit_normalization_event,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    candidate = Candidate(
        scope="entity",
        record={"population": 2},
        evidence={},
    )

    payload = unit_normalization_event(
        record_id="row-2",
        pointer="/population",
        original_value=2,
        unit=CanonicalUnit(
            dimension="count",
            base_unit="person",
            multiplier=1_000,
        ),
    )

    assert payload is not None

    events = [{"payload": payload}]

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="static",
            unit_sensitive=True,
            comparable_across_rows=True,
            confidence=1.0,
            basis="deterministic",
        )
    }

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-2",
                "candidate": candidate.model_dump(mode="json"),
            },
        ],
        events=lambda _rid, kind: (events if kind == "unit_normalization" else []),
        event=lambda *_args: pytest.fail("duplicate normalization persisted"),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        lambda: (
            {
                "record_id": "row-2",
                "pointer": "/population",
                "observed_canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1_000,
                },
            },
            {
                "record_id": "row-1",
                "pointer": "/population",
                "observed_canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
            },
        ),
    )

    assert runner.ensure_unit_normalizations() == 0


def _e6e_unit_semantics():
    from verboisy.core.fitness import (
        FieldSemantics,
    )

    return {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="static",
            unit_sensitive=True,
            comparable_across_rows=True,
            confidence=1.0,
            basis="deterministic",
        )
    }


def _e6e_unit_observations():
    return (
        {
            "record_id": "row-1",
            "pointer": "/population",
            "observed_canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1,
            },
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1,
            },
        },
        {
            "record_id": "row-2",
            "pointer": "/population",
            "unit": {
                "label": "thousands of persons",
            },
            "observed_canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
        },
    )


def test_comparability_observation_handles_missing_record_pointer(
    monkeypatch,
):
    from types import SimpleNamespace

    import verboisy.core.dataset_consistency as inspection
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimComparability,
        GroundedComparabilityDescriptor,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={"population": 2},
        evidence={},
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T12:00:00+00:00",
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    monkeypatch.setattr(
        inspection,
        "claim_comparability_from_events",
        lambda *_args, **_kwargs: {
            "/missing": GroundedClaimComparability(
                unit=GroundedComparabilityDescriptor(
                    label="thousands of persons",
                    source="metadata",
                    quote="thousands of persons",
                )
            )
        },
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.store = SimpleNamespace(
        events=lambda *_args: [],
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": candidate.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json"),
            }
        ],
    )

    observation = runner.dataset_comparability_observations()[0]

    assert "normalized_value" not in observation
    assert observation["canonical_unit"]["multiplier"] == 1_000


def test_comparability_observation_replays_normalized_value(
    monkeypatch,
):
    from types import SimpleNamespace

    import verboisy.core.dataset_consistency as inspection
    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimComparability,
        GroundedComparabilityDescriptor,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={"population": 2},
        evidence={},
    )

    snapshot = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T12:00:00+00:00",
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    monkeypatch.setattr(
        inspection,
        "claim_comparability_from_events",
        lambda *_args, **_kwargs: {
            "/population": (
                GroundedClaimComparability(
                    unit=GroundedComparabilityDescriptor(
                        label="thousands of persons",
                        source="metadata",
                        quote="thousands of persons",
                    )
                )
            )
        },
    )

    monkeypatch.setattr(
        inspection,
        "normalized_unit_value_from_events",
        lambda *_args, **_kwargs: 2_000,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.store = SimpleNamespace(
        events=lambda *_args: [],
        evidence=lambda _rid: [
            {
                "record_id": "row-1",
                "candidate": candidate.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json"),
            }
        ],
    )

    observation = runner.dataset_comparability_observations()[0]

    assert observation["normalized_value"] == 2_000

    assert observation["observed_canonical_unit"]["multiplier"] == 1_000

    assert observation["canonical_unit"]["multiplier"] == 1


@pytest.mark.parametrize(
    "store",
    [
        # First capability missing.
        SimpleNamespace(),
        # First present, second missing.
        SimpleNamespace(
            evidence=lambda _rid: [],
        ),
        # First two present, writer missing.
        SimpleNamespace(
            evidence=lambda _rid: [],
            events=lambda *_args: [],
        ),
    ],
)
def test_unit_normalization_supports_legacy_store(
    store,
):
    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.store = store

    assert runner.ensure_unit_normalizations() == 0


def test_unit_normalization_returns_when_no_scale_gap(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _e6e_unit_semantics()
    runner.store = SimpleNamespace(
        evidence=lambda _rid: [],
        events=lambda *_args: [],
        event=lambda *_args: None,
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        lambda: (
            {
                "record_id": "row-1",
                "pointer": "/population",
                "canonical_unit": {
                    "dimension": "count",
                    "base_unit": "person",
                    "multiplier": 1,
                },
            },
        ),
    )

    assert runner.ensure_unit_normalizations() == 0


@pytest.mark.parametrize(
    "invalid_observation",
    [
        # Invalid record ID.
        {
            "record_id": 123,
            "pointer": "/population",
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
        },
        # Invalid pointer.
        {
            "record_id": "row-x",
            "pointer": 123,
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
        },
        # Valid shape, unrelated pointer.
        {
            "record_id": "row-x",
            "pointer": "/other",
            "canonical_unit": {
                "dimension": "count",
                "base_unit": "person",
                "multiplier": 1_000,
            },
        },
    ],
)
def test_unit_normalization_skips_irrelevant_observation(
    monkeypatch,
    invalid_observation,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    events = []

    first = Candidate(
        scope="entity",
        record={"population": 100},
        evidence={},
    )
    second = Candidate(
        scope="entity",
        record={"population": 2},
        evidence={},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _e6e_unit_semantics()

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-1",
                "candidate": first.model_dump(mode="json"),
            },
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-2",
                "candidate": second.model_dump(mode="json"),
            },
        ],
        events=lambda *_args: events,
        event=lambda _rid, _kind, payload: (events.append({"payload": payload})),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        lambda: (
            *_e6e_unit_observations(),
            invalid_observation,
        ),
    )

    assert runner.ensure_unit_normalizations() == 1


def test_unit_normalization_skips_missing_candidate(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    first = Candidate(
        scope="entity",
        record={"population": 100},
        evidence={},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _e6e_unit_semantics()

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-1",
                "candidate": first.model_dump(mode="json"),
            }
        ],
        events=lambda *_args: [],
        event=lambda *_args: pytest.fail("normalization must not persist"),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        _e6e_unit_observations,
    )

    assert runner.ensure_unit_normalizations() == 0


def test_unit_normalization_skips_missing_value_pointer(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    first = Candidate(
        scope="entity",
        record={"population": 100},
        evidence={},
    )

    second = Candidate(
        scope="entity",
        record={"other": 2},
        evidence={},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _e6e_unit_semantics()

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-1",
                "candidate": first.model_dump(mode="json"),
            },
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-2",
                "candidate": second.model_dump(mode="json"),
            },
        ],
        events=lambda *_args: [],
        event=lambda *_args: pytest.fail("normalization must not persist"),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        _e6e_unit_observations,
    )

    assert runner.ensure_unit_normalizations() == 0


def test_unit_normalization_skips_non_numeric_value(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    first = Candidate(
        scope="entity",
        record={"population": 100},
        evidence={},
    )

    second = Candidate(
        scope="entity",
        record={"population": "two"},
        evidence={},
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.field_semantics = _e6e_unit_semantics()

    runner.store = SimpleNamespace(
        evidence=lambda _rid: [
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-1",
                "candidate": first.model_dump(mode="json"),
            },
            {
                "snapshot": {"id": "fixture-snapshot"},
                "record_id": "row-2",
                "candidate": second.model_dump(mode="json"),
            },
        ],
        events=lambda *_args: [],
        event=lambda *_args: pytest.fail("normalization must not persist"),
    )

    monkeypatch.setattr(
        runner,
        "dataset_comparability_observations",
        _e6e_unit_observations,
    )

    assert runner.ensure_unit_normalizations() == 0


def test_target_met_reloads_rows_after_normalization(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from verboisy.core.research import (
        ResearchRunner,
    )
    from verboisy.extractor.schema_builder import (
        SchemaBuilder,
    )

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.task = SimpleNamespace(
        target_records=1,
    )
    runner.schema = {
        "type": "array",
    }

    runner.store = SimpleNamespace(
        records=MagicMock(
            side_effect=[
                [
                    {
                        "id": "row-1",
                        "population": 2,
                    }
                ],
                [
                    {
                        "id": "row-1",
                        "population": 2_000,
                    }
                ],
            ]
        ),
        summary=lambda _rid: {
            "identity_conflicts": 0,
        },
    )

    monkeypatch.setattr(
        runner,
        "dataset_consistency_gaps",
        lambda: (),
    )

    validator = SimpleNamespace(
        is_valid=lambda rows: rows
        == [
            {
                "population": 2_000,
            }
        ],
    )

    monkeypatch.setattr(
        SchemaBuilder,
        "validator",
        lambda _schema: validator,
    )

    assert runner.target_met()
    assert runner.store.records.call_count == 2
