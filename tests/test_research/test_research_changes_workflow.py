# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Broader alternatives pause before export and honor both resume decisions."""

import json
from unittest.mock import AsyncMock

import pytest
from verboisy.api import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.storage.changes import pending_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_extractor.test_range_changes import SCHEMA
from tests.test_research.test_contracts import PAGES


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["accept", "decline", "valid"])
async def test_scope_and_columns_offer_and_resume(world, tmp_path, monkeypatch, decision):
    url = "https://people.test/cities"
    monkeypatch.setitem(PAGES, url, "<article><h1>Example</h1><p>City restrictions</p></article>")
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "runs.db"),
        search_provider="disabled",
        action_delay_seconds=0,
    )
    task = TaskSpec(seed_urls=[url], target_records=1, settle_ms=0, max_interactions_per_page=0)
    calls = []

    async def complete(self, system, prompt):
        payload = json.loads(prompt)
        calls.append(payload)
        if "candidate" in payload:
            return {
                "relevant": True,
                "same_entity": True,
                "supported_fields": list(payload["candidate"]["evidence"]),
                "rejected_fields": [],
            }
        name = next(s for s in payload["sources"] if s["text"] == "Example")
        source = next(s for s in payload["sources"] if "City restrictions" in s["text"])
        accepted = "city" in payload["schema"]["properties"]
        candidate = {
            "scope": name["scope"],
            "record": {"name": "Example", "city": "City restrictions"}
            if accepted
            else {"name": "Example", "weight": None},
            "evidence": {"/name": {"source": name["id"], "quote": "Example", "transform": "text"}},
        }
        if accepted:
            candidate["evidence"]["/city"] = {
                "source": source["id"],
                "quote": "City restrictions",
                "transform": "text",
            }
        return {
            "candidates": [candidate] if accepted or decision == "valid" else [],
            "research_suggestions": [
                {
                    "goal": "Research city restrictions",
                    "columns": {"city": {"type": "string"}},
                    "drop_columns": ["weight"],
                    "evidence": [
                        {
                            "pointer": pointer,
                            "scope": source["scope"],
                            "source": source["id"],
                            "quote": "City restrictions",
                        }
                        for pointer in ["/", "/city", "/weight"]
                    ],
                }
            ],
        }

    monkeypatch.setattr(LLMClient, "complete_json", complete)
    monkeypatch.setattr(ResearchRunner, "ensure_field_semantics", AsyncMock())
    output = tmp_path / "rows.json"
    first = await arun(
        goal="Typical weights", schema=SCHEMA, task=task, config=config, export=output, max_steps=1
    )
    if decision == "valid":
        assert first.completed and output.exists()
        store = ResearchStore(config.sqlite_db_path, read_only=True)
        assert pending_change(store, first.run_id) is None
        store.close()
        return
    assert first.stop_reason == "proposed_changes" and first.export_path is None
    assert not output.exists() and len(calls) == 1
    assert any("Added columns" in notice for notice in first.notices)
    result = await arun(
        **({"okresume": first.run_id} if decision == "accept" else {"resume": first.run_id}),
        config=config,
        max_steps=1,
    )
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    assert len(store.events(first.run_id, "change_proposed")) == 1
    assert pending_change(store, first.run_id) is None
    assert store.load(first.run_id)["goal"] == (
        "Research city restrictions" if decision == "accept" else "Typical weights"
    )
    store.close()
    if decision == "accept":
        assert result.completed and result.records[0]["city"] == "City restrictions"
        assert "weight" not in json.loads(output.read_text())[0]
    else:
        assert not result.completed and result.records == []
        assert result.stop_reason != "proposed_changes"
