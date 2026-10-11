# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public API ingestion uses real loopback HTTP and exact persisted row evidence."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import FieldRule, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.extractor.ingestion import row_evidence, run_dataset_sources
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_dataset_assets import capture


@pytest.fixture
def site(tmp_path):
    bodies, seen = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802 - standard server interface
            seen.append(self.path)
            status, body = bodies.get(self.path, (404, b"missing"))
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        allow_private_network=True,
        allowed_domains=["127.0.0.1"],
        search_provider="disabled",
        openai_api_key=None,
        anthropic_api_key=None,
        litellm_api_key=None,
        model_request_budget=1,
    )
    try:
        yield base, bodies, seen, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def schema(fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def task(url, fmt="json", target=2, **extra):
    return {"dataset_sources": [{"url": url, "format": fmt}], "target_records": target, **extra}


@pytest.fixture(autouse=True)
def no_paid_or_browser_work():
    with (
        patch(
            "verboisy.browser.context.BrowserManager.start",
            new=AsyncMock(side_effect=AssertionError("browser")),
        ),
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            new=AsyncMock(side_effect=AssertionError("model")),
        ),
        patch("verboisy.api.web_search", new=AsyncMock(side_effect=AssertionError("search"))),
    ):
        yield


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", 'name,note\r\nAnaïs,"first\nsecond"\r\n李雷,\r\nthird,=1+1\r\n'.encode()),
        (
            "json",
            '[{"name":"Anaïs","note":"first\\nsecond"},{"name":"李雷","note":""},{"name":"third","note":"=1+1"}]'.encode(),
        ),
        (
            "jsonl",
            '\n{"name":"Anaïs","note":"first\\nsecond"}\n\n{"name":"李雷","note":""}\n{"name":"third","note":"=1+1"}\n'.encode(),
        ),
    ],
)
async def test_public_run_ingests_exact_rows_and_resumes_without_fetch(site, tmp_path, fmt, body):
    base, bodies, seen, config = site
    bodies["/data"] = (200, body)
    target_schema = schema({"name": {"type": "string"}, "note": {"type": "string"}})
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Read fixture records",
        schema=target_schema,
        task=task(base + "/data", fmt),
        config=config,
        export=output,
        proof=True,
    )
    assert result.completed
    assert result.records == [
        {"id": 1, "name": "Anaïs", "note": "first\nsecond"},
        {"id": 2, "name": "李雷", "note": ""},
    ]
    store = ResearchStore(config.sqlite_db_path)
    try:
        saved = store.dataset_assets(result.run_id)
        before, evidence, events = (
            store.load(result.run_id),
            store.evidence(result.run_id),
            store.events(result.run_id),
        )
        assert len(saved) == 1 and len(saved[0].download.dataset.rows) == 3
        assert saved[0].download.dataset.original_bytes == body
        assert len(store.events(result.run_id, "dataset_row")) == 2
        for index, item in enumerate(evidence, 1):
            assert item["snapshot"]["dataset_asset_id"] == saved[0].id
            assert item["snapshot"]["dataset_row_index"] == index
            assert item["candidate"]["evidence"]["/name"]["transform"] == "dataset"
        assert before["tokens"] == before["reserved"] == 0
    finally:
        store.close()
    bodies.clear()
    for _ in range(2):
        resumed = await arun(resume=result.run_id, config=config, export=output)
        assert resumed.records == result.records and resumed.completed
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.load(result.run_id) == before
        assert store.evidence(result.run_id) == evidence
        assert store.events(result.run_id) == events
    finally:
        store.close()
    assert seen == ["/data"]
    assert json.loads(output.read_text()) == result.records


async def test_native_json_types_nested_pointers_and_urls(site):
    base, bodies, _, config = site
    value = {
        "number": 10**40 + 1,
        "fraction": 1e-9,
        "flag": True,
        "null": None,
        "nested": {"a/b": ["李雷", {}]},
        "url": "https://example.test/Item",
    }
    bodies["/data"] = (200, json.dumps([value]).encode())
    fields = {
        "number": {"type": "integer"},
        "fraction": {"type": "number"},
        "flag": {"type": "boolean"},
        "null": {"type": "null"},
        "nested": {"type": "object", "additionalProperties": True},
        "url": {"type": "string"},
    }
    result = await arun(
        goal="Read values",
        schema=schema(fields),
        task=task(base + "/data", target=1),
        config=config,
    )
    assert result.completed and result.records == [{"id": 1, **value}]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert "/nested/a~1b/0" in store.evidence(result.run_id)[0]["candidate"]["evidence"]
    finally:
        store.close()


async def test_source_budget_resume_replays_first_source(site):
    base, bodies, seen, config = site
    bodies.update({"/one": (200, b'[{"name":"one"}]'), "/two": (200, b'[{"name":"two"}]')})
    spec = task(base + "/one")
    spec["dataset_sources"].extend(
        [
            {"url": base + "/two", "format": "json"},
            {"url": base + "/unused", "format": "json"},
        ]
    )
    first = await arun(
        goal="Read names",
        schema=schema({"name": {"type": "string"}}),
        task=spec,
        config=config,
        max_steps=1,
    )
    assert not first.completed and first.stop_reason == "dataset_source_budget"
    second = await arun(resume=first.run_id, config=config, max_steps=1)
    assert second.completed and [row["name"] for row in second.records] == ["one", "two"]
    assert seen == ["/one", "/two"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(first.run_id, "dataset_row")) == 2
    finally:
        store.close()


@pytest.mark.parametrize(
    "fmt,body,fields,expected",
    [
        ("csv", b"number\n2\n", {"number": {"type": "integer"}}, "dataset_row_gaps"),
        ("json", b'[{"wrong":"field"}]', {"name": {"type": "string"}}, "dataset_row_gaps"),
        ("json", b"[]", {"name": {"type": "string"}}, "observed_scope_exhausted"),
        ("json", b'[{"name":NaN}]', {"name": {"type": "string"}}, "dataset_source_failure"),
    ],
)
async def test_invalid_or_empty_rows_never_complete(site, fmt, body, fields, expected):
    base, bodies, _, config = site
    bodies["/data"] = (200, body)
    result = await arun(
        goal="Read rows", schema=schema(fields), task=task(base + "/data", fmt, 1), config=config
    )
    assert not result.completed and result.records == [] and result.stop_reason == expected


async def test_source_failure_is_retryable(site):
    base, bodies, seen, config = site
    first = await arun(
        goal="Read names",
        schema=schema({"name": {"type": "string"}}),
        task=task(base + "/data", target=1),
        config=config,
    )
    assert first.status == "FAILED"
    bodies["/data"] = (200, b'[{"name":"fixed"}]')
    resumed = await arun(resume=first.run_id, config=config)
    assert resumed.completed and seen == ["/data", "/data"]


async def test_declared_sources_respect_scope_before_fetch(site):
    base, bodies, seen, config = site
    bodies["/data"] = (200, b'[{"name":"wrong"}]')
    result = await arun(
        goal="Read names",
        schema=schema({"name": {"type": "string"}}),
        task=task(base + "/data", target=1, exclude_paths=["/data"]),
        config=config,
    )
    assert result.stop_reason == "dataset_source_failure" and seen == []


async def test_dataset_rows_do_not_bypass_unit_comparability(site):
    base, bodies, _, config = site
    bodies["/data"] = (200, b'[{"population":2}]')
    result = await arun(
        goal="Read population",
        schema=schema(
            {
                "population": {
                    "type": "integer",
                    "x-verboisy-temporal-class": "static",
                    "x-verboisy-unit-sensitive": True,
                    "x-verboisy-comparable-across-rows": True,
                }
            }
        ),
        task=task(base + "/data", target=1),
        config=config,
    )
    assert not result.completed and result.stop_reason == "dataset_consistency_gaps"


async def test_identity_conflict_is_not_entity_completion(site):
    base, bodies, _, config = site
    bodies["/data"] = (
        200,
        b'[{"name":"same","value":1},{"name":"same","value":2},{"name":"other","value":3}]',
    )
    result = await arun(
        goal="Read values",
        schema=schema({"name": {"type": "string"}, "value": {"type": "integer"}}),
        task=task(base + "/data", identity_fields=["/name"]),
        config=config,
    )
    assert not result.completed and result.stop_reason == "dataset_row_gaps"
    assert [row["name"] for row in result.records] == ["other"]


async def test_mixed_browser_sources_rejected_before_network(site):
    base, _, seen, config = site
    with pytest.raises(VerboisyError, match="mixed"):
        await arun(
            goal="Read names",
            schema=["name"],
            task=task(base + "/data", seed_urls=[base]),
            config=config,
        )
    assert seen == []


@pytest.mark.parametrize(
    "change,expected",
    [
        ("ungrounded", "dataset_proof_not_grounded"),
        ("rule", "dataset_rule_not_supported"),
        ("quote", "unsupported_dataset_value"),
        ("value", "unsupported_dataset_value"),
    ],
)
def test_dataset_proof_checks_exact_value_and_authority(tmp_path, change, expected):
    store = ResearchStore(str(tmp_path / "proof.db"))
    try:
        rid = store.create("Read rows", {}, TaskSpec(), None)
        asset_id = store.save_dataset_asset(rid, capture())
        asset = store.load_dataset_asset(rid, asset_id)
        page, candidate = row_evidence(asset, asset.download.dataset.rows[0])
        spec = TaskSpec()
        if change == "ungrounded":
            page = page.model_copy(update={"dataset_asset_id": None})
        elif change == "rule":
            spec.field_rules["/name"] = FieldRule(source="link")
        elif change == "quote":
            candidate.evidence["/name"].quote = '"wrong"'
        else:
            candidate.record["name"] = "wrong"
        reasons = verify(
            candidate, page, schema({"name": {"type": "string"}, "note": {"type": "string"}}), spec
        )
        assert f"/name:{expected}" in reasons
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure,reason",
    [
        (TimeoutError(), "run_timeout"),
        (asyncio.CancelledError(), "interrupted"),
    ],
)
async def test_run_interruption_preserves_resumable_state(tmp_path, failure, reason):
    store = ResearchStore(str(tmp_path / "interruption.db"))
    try:
        rid = store.create(
            "Read rows",
            schema({"name": {"type": "string"}}),
            TaskSpec.model_validate(task("https://example.test/data", target=1)),
            None,
        )
        runner = ResearchRunner(store, rid, Settings(_env_file=None))
        with patch(
            "verboisy.extractor.ingestion.download_dataset", new=AsyncMock(side_effect=failure)
        ):
            if isinstance(failure, asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await run_dataset_sources(runner, 1)
            else:
                assert await run_dataset_sources(runner, 1) == ("PAUSED", reason)
        assert store.load(rid)["reason"] == reason
    finally:
        store.close()


async def test_corrupted_asset_fails_closed_on_resume(tmp_path):
    store = ResearchStore(str(tmp_path / "corrupt.db"))
    try:
        rid = store.create(
            "Read rows",
            schema({"name": {"type": "string"}}),
            TaskSpec.model_validate(task("https://example.test/start", "csv", 1)),
            None,
        )
        store.save_dataset_asset(rid, capture())
        store.db.execute("UPDATE dataset_blobs SET content=?", (b"wrong",))
        store.db.commit()
        runner = ResearchRunner(store, rid, Settings(_env_file=None))
        assert await run_dataset_sources(runner, 1) == ("FAILED", "dataset_asset_integrity")
    finally:
        store.close()


async def test_duplicate_rows_and_unbounded_target_do_not_claim_completion(site):
    base, bodies, seen, config = site
    bodies["/data"] = (200, b'[{"name":"same"},{"name":"same"},{"name":"other"}]')
    result = await arun(
        goal="Read rows",
        schema=schema({"name": {"type": "string"}}),
        task=task(base + "/data", target=None),
        config=config,
    )
    assert not result.completed and result.status == "EXHAUSTED"
    assert [row["name"] for row in result.records] == ["same", "other"]
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records and seen == ["/data"]


@pytest.mark.parametrize("stage", ["snapshot", "accepted", "bad_binding", "changed_snapshot"])
async def test_resume_reconciles_interrupted_row_capture(tmp_path, stage):
    config = Settings(_env_file=None, sqlite_db_path=str(tmp_path / "reconcile.db"))
    store = ResearchStore(config.sqlite_db_path)
    try:
        spec = TaskSpec.model_validate(task("https://example.test/start", "csv", 1))
        target_schema = schema({"name": {"type": "string"}, "note": {"type": "string"}})
        rid = store.create("Read rows", target_schema, spec, None)
        asset_id = store.save_dataset_asset(rid, capture())
        asset = store.load_dataset_asset(rid, asset_id)
        page, candidate = row_evidence(asset, asset.download.dataset.rows[0])
        if stage == "bad_binding":
            page = page.model_copy(update={"dataset_asset_id": "missing"})
        elif stage == "changed_snapshot":
            page = page.model_copy(update={"content_hash": "changed"})
        store.queue(rid, page.url, 0, None)
        work = store.next_page(rid)
        store.snapshot(rid, work["id"], page, "", "")
        if stage != "snapshot":
            assert store.accept(rid, page, candidate, [], spec) == "accepted"
    finally:
        store.close()
    with patch(
        "verboisy.extractor.ingestion.download_dataset",
        new=AsyncMock(side_effect=AssertionError("refetch")),
    ):
        result = await arun(resume=rid, config=config)
    if stage in {"bad_binding", "changed_snapshot"}:
        assert not result.completed and result.stop_reason == "dataset_asset_integrity"
    else:
        assert result.completed and result.records == [{"id": 1, **candidate.record}]
        store = ResearchStore(config.sqlite_db_path)
        try:
            assert len(store.events(rid, "dataset_row")) == 1
        finally:
            store.close()
