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
    with pytest.raises(VerboisyError, match="seed URLs"):
        await arun(goal="Find customers", schema=schema, config=config)
    config.search_provider = "brave"
    search = AsyncMock(
        return_value=SearchObservation(
            query="customers", results=[SearchResult(title="leads", url="https://people.test/")]
        )
    )
    monkeypatch.setattr("verboisy.api.brave_search", search)
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


async def test_invalid_proposal_response_does_not_block_link_discovery(config, world, monkeypatch):
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
        "queued",
        "https://people.test/",
    )
    assert pages["https://people.test/b"] == (
        "queued",
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

    assert resumed.records == [
        {"customer": "Alice", "age": 31},
        {"customer": "Bob", "age": 22},
    ]

    assert first_record in resumed.records
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
    assert result.records == [{"customer": "same-id", "age": 31}]

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
