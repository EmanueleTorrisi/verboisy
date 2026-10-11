# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A range conflict pauses before reviews and exports; accepting continues exact strings."""

import json
from unittest.mock import AsyncMock

import pytest
from verboisy.api import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import Candidate, Snapshot, Source, TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.storage.changes import pending_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_extractor.test_range_changes import SCHEMA
from tests.test_research.test_contracts import PAGES


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [True, False])
async def test_live_range_conflict_pauses_then_honors_decision(
    world, tmp_path, monkeypatch, accept
):
    url = "https://people.test/range"
    monkeypatch.setitem(
        PAGES, url, "<article><h1>Example</h1><p>Male weight: 45 - 55 kg.</p></article>"
    )
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "runs.db"),
        search_provider="disabled",
        action_delay_seconds=0,
    )
    task = TaskSpec(
        seed_urls=[url],
        target_records=1,
        settle_ms=0,
        max_interactions_per_page=0,
        identity_fields=["/name"],
    )
    calls = []

    async def complete(self, system, prompt):
        payload = json.loads(prompt)
        calls.append(payload)
        if "candidate" in payload:
            return {
                "relevant": True,
                "same_entity": True,
                "supported_fields": ["/name", "/weight"],
                "rejected_fields": [],
            }
        sources = payload["sources"]
        name = next(s for s in sources if s["text"] == "Example")
        weight = next(s for s in sources if "45 - 55 kg" in s["text"])
        field = payload["schema"]["properties"]["weight"]["type"]
        string = "string" in field
        candidate = {
            "scope": name["scope"],
            "record": {
                "name": "Example",
                "weight": "45 - 55 kg" if string else 50,
            },
            "evidence": {
                "/name": {"source": name["id"], "quote": "Example", "transform": "text"},
                "/weight": {
                    "source": weight["id"],
                    "quote": "45 - 55 kg",
                    "transform": "text" if string else "number",
                },
            },
        }
        return {
            "candidates": [candidate],
            "priority_links": [],
            "range_conflicts": []
            if string
            else [
                {
                    "pointer": "/weight",
                    "scope": name["scope"],
                    "source": weight["id"],
                    "quote": "45 - 55 kg",
                }
            ],
        }

    monkeypatch.setattr(LLMClient, "complete_json", complete)
    monkeypatch.setattr(ResearchRunner, "ensure_field_semantics", AsyncMock())
    output = tmp_path / "weights.json"
    first = await arun(
        goal="Typical weights", schema=SCHEMA, task=task, config=config, export=output, max_steps=1
    )
    assert first.status == "PAUSED" and first.stop_reason == "proposed_changes"
    assert first.records == [] and first.export_path is None and not output.exists()
    assert any("--okresume" in notice for notice in first.notices)
    assert all(notice.startswith("* ") for notice in first.notices)
    assert len(calls) == 1  # No review or assessment after the conflict.
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    assert pending_change(store, first.run_id) is not None
    assert len(store.events(first.run_id, "extraction_proposal")) == 1
    assert store.events(first.run_id, "extraction_proposal")[0]["payload"]["proposal"][
        "range_conflicts"
    ]
    assert store.records(first.run_id) == []
    store.close()

    result = await arun(
        **({"okresume": first.run_id} if accept else {"resume": first.run_id}),
        config=config,
        max_steps=1,
    )
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    assert len(store.events(first.run_id, "change_proposed")) == 1
    assert pending_change(store, first.run_id) is None
    store.close()
    if accept:
        assert result.completed
        assert result.records[0]["weight"] == "45 - 55 kg"
        assert json.loads(output.read_text())[0]["weight"] == "45 - 55 kg"
        assert len(calls) == 3  # New proposal plus independent semantic review.
    else:
        assert not result.completed and result.records == []
        assert result.stop_reason != "proposed_changes"
        assert len(calls) == 2  # Rejected numeric proof never reaches review.


@pytest.mark.asyncio
async def test_saved_interval_offered_before_browser_or_model(tmp_path, monkeypatch):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    rid = store.create("Typical weights", SCHEMA, TaskSpec(), None)
    store.event(rid, "product_options", {})
    page = Snapshot(
        id="saved",
        url="https://example.test/",
        fetched_at="2026-01-01",
        content_hash="fixture",
        truncated=False,
        sources=[Source(id="e1", scope="s1", kind="text", text="Male weight: 45 - 55 kg")],
    )
    candidate = Candidate(
        scope="s1",
        record={"name": "Example", "weight": 50},
        evidence={"/weight": {"source": "e1", "quote": "45 - 55 kg", "transform": "number"}},
    )
    captured = page
    store.queue(rid, captured.url, 0, None)
    work = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()
    store.snapshot(rid, work["id"], captured, "Male weight: 45 - 55 kg")
    store.db.execute(
        "INSERT INTO candidates(run_id,snapshot_id,payload,accepted) VALUES (?,?,?,0)",
        (rid, page.id, candidate.model_dump_json()),
    )
    store.db.commit()
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    store.close()
    execute = AsyncMock(side_effect=AssertionError("Research must not start"))
    monkeypatch.setattr(ResearchRunner, "run", execute)
    monkeypatch.setattr(LLMClient, "complete_json", execute)
    result = await arun(
        resume=rid,
        config=Settings(_env_file=None, sqlite_db_path=str(path), model_request_budget=1),
    )
    assert result.stop_reason == "proposed_changes" and result.export_paths == ()
    execute.assert_not_awaited()
    store = ResearchStore(str(path), read_only=True)
    state = store.load(rid)
    assert (state["tokens"], state["reserved"]) == (17, 796)
    assert json.loads(state["schema_json"]) == SCHEMA
    store.close()


@pytest.mark.asyncio
async def test_missing_proposal_for_pause_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    rid = store.create("Goal", SCHEMA, TaskSpec(), None)
    store.close()

    async def inconsistent(runner, steps):
        runner.store.finish(rid, "PAUSED", "proposed_changes", 0, 0)

    monkeypatch.setattr(ResearchRunner, "run", inconsistent)
    with pytest.raises(VerboisyError, match="proposal is missing"):
        await arun(resume=rid, config=Settings(_env_file=None, sqlite_db_path=str(path)))
