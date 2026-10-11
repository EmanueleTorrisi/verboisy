# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Captured source profiles persist once and accompany portable event history."""

import json

import pytest
from verboisy import arun
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research.test_dataset_projection_ingestion import PLAN, SCHEMA

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.asyncio
async def test_profile_journal_portable_and_resume(site, tmp_path):
    base, bodies, seen, config = site
    bodies["/first"] = (200, b'[{"Person":"A","Age":"31","unused":"literal"}]')
    bodies["/second"] = (200, b'[{"Person":"B","Age":"22"}]')
    sources = [
        {"url": base + path, "format": "json", "projection": PLAN} for path in ["/first", "/second"]
    ]
    output = tmp_path / "rows.json"
    first = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=sources,
        maxrows=2,
        max_steps=1,
        export=output,
        config=config,
    )
    assert first.stop_reason == "dataset_source_budget"
    store = ResearchStore(config.sqlite_db_path)
    try:
        events = store.events(first.run_id, "dataset_profile")
        assert len(events) == 1
        asset = store.dataset_assets(first.run_id)[0]
        payload = events[0]["payload"]
        assert payload["asset_id"] == asset.id
        profile = payload["profile"]
        assert profile["asset_sha256"] == asset.download.dataset.sha256
        assert profile["sampled_rows"] == profile["total_rows"] == 1
        assert profile["profile_version"] == "1"
        fields = {field["pointer"]: field for field in profile["fields"]}
        assert fields["/Age"]["observed_types"] == ["string"]
        assert fields["/unused"]["examples"][0]["json_preview"] == '"literal"'
    finally:
        store.close()
    second = await arun(resume=first.run_id, export=output, config=config)
    assert second.completed
    third = await arun(resume=first.run_id, export=output, config=config)
    assert third.records == second.records
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(first.run_id, "dataset_profile")) == 2
    finally:
        store.close()
    portable = json.loads(output.with_suffix(".json.events.json").read_text())
    # Event sidecars contain the full journal, including profiles of raw source columns.
    assert len([event for event in portable["events"] if event["kind"] == "dataset_profile"]) == 2
    assert seen == ["/first", "/second"]


@pytest.mark.asyncio
async def test_same_capture_multiple_plans_gets_one_profile(site):
    base, bodies, seen, config = site
    bodies["/rows"] = (200, b'[{"first":"A","second":"B"}]')
    sources = [
        {
            "url": base + "/rows",
            "format": "json",
            "projection": {
                "fields": [{"source": pointer, "target": "/name"}],
            },
        }
        for pointer in ["/first", "/second"]
    ]
    result = await arun(
        goal="Names",
        schema=fixtures.schema({"name": {"type": "string"}}),
        dataset_sources=sources,
        maxrows=2,
        config=config,
    )
    assert result.completed
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(result.run_id, "dataset_profile")) == 1
        assert len(store.dataset_assets(result.run_id)) == 1
    finally:
        store.close()
    assert seen == ["/rows"]


@pytest.mark.asyncio
async def test_interruption_before_profile_commit_reuses_capture(site):
    from unittest.mock import patch

    base, bodies, seen, config = site
    bodies["/rows"] = (200, b'[{"name":"A"}]')
    original = ResearchStore.event

    def interrupted(self, rid, kind, payload):
        if kind == "dataset_profile":
            raise RuntimeError("profile checkpoint")
        return original(self, rid, kind, payload)

    with (
        patch.object(ResearchStore, "event", interrupted),
        pytest.raises(RuntimeError, match="checkpoint"),
    ):
        await arun(
            goal="Names",
            schema=fixtures.schema({"name": {"type": "string"}}),
            dataset_sources=[{"url": base + "/rows", "format": "json"}],
            maxrows=1,
            config=config,
        )
    store = ResearchStore(config.sqlite_db_path)
    try:
        rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
        assert len(store.dataset_assets(rid)) == 1
        assert store.events(rid, "dataset_profile") == []
    finally:
        store.close()
    result = await arun(resume=rid, config=config)
    assert result.completed
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(rid, "dataset_profile")) == 1
    finally:
        store.close()
    assert seen == ["/rows"]
