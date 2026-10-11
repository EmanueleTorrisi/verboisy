# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared dataset period repairs use eligible run intent and current evidence bindings."""

import json
from dataclasses import replace

import pytest
from verboisy import arun
from verboisy.core.planner import TemporalIntent
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.extractor.ingestion import row_evidence
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_dataset_year_repair as years
from tests.test_research import test_temporal_projection_ingestion as temporal
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.parametrize(
    "case",
    [
        "latest",
        "year",
        "range",
        "explicit",
        "slow_changing",
        "preferred",
        "static",
        "event",
        "time_series",
        "unknown",
        "noncomparable",
        "browser",
    ],
)
def test_scope_period_policy_and_current_bindings(tmp_path, case):
    store = ResearchStore(str(tmp_path / "run.db"))
    task = TaskSpec(
        identity_fields=["/name"],
        dataset_sources=[]
        if case == "browser"
        else [{"url": "https://example.test/data", "format": "json"}],
    )
    rid = store.create("Latest population", temporal.schema(True, True), task, None)
    try:
        aid = store.save_dataset_asset(
            rid, capture(json.dumps(temporal.rows()[:1]).encode(), "json")
        )
        asset = store.load_dataset_asset(rid, aid)
        page, candidate = row_evidence(
            asset,
            asset.download.dataset.rows[0],
            ProjectionPlan.model_validate(years.undated_plan()),
        )
        store.queue(rid, page.url, 0, None)
        work = store.db.execute(
            "SELECT id FROM pages WHERE run_id=? AND url=?", (rid, page.url)
        ).fetchone()
        store.snapshot(rid, work[0], page, "fixture")
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        field = runner.field_semantics["/population"]
        if case in {"slow_changing", "static", "event", "time_series", "unknown"}:
            field = replace(field, temporal_class=case)
        if case == "preferred":
            field = replace(field, reference_period="preferred")
        if case == "noncomparable":
            field = replace(field, comparable_across_rows=False)
        if case == "explicit":
            field = replace(field, temporal_intent=TemporalIntent(mode="year", start_year=2023))
        runner.field_semantics["/population"] = field
        if case == "year":
            runner.temporal_intent = TemporalIntent(mode="year", start_year=2024)
        if case == "range":
            runner.temporal_intent = TemporalIntent(mode="range", start_year=2023, end_year=2025)
        events = store.events(rid)
        repairs = runner.dataset_consistency_repairs()
        expected = case in {"latest", "year", "explicit", "slow_changing"}
        assert len(repairs) == int(expected)
        assert runner.field_semantics["/population"] == field
        assert store.events(rid) == events
        if expected:
            repair = repairs[0]
            assert repair["reason"] == "missing_reference_period"
            assert repair["pointer"] == "/population" and repair["observed_year"] is None
            assert repair["target_mode"] == ("year" if case in {"year", "explicit"} else "latest")
            assert repair["target_year"] == (
                2024 if case == "year" else 2023 if case == "explicit" else None
            )
            assert repair["snapshot_id"] == page.id
            assert repair["record_id"] == store.evidence(rid)[0]["record_id"]
            assert isinstance(repair["candidate_key"], str)
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal,mode,target",
    [
        ("Latest population", "latest", None),
        ("Population in 2024", "year", 2024),
        ("Population from 2023 to 2025", None, None),
    ],
)
async def test_public_period_repair_request_is_portable_and_clears(
    site, tmp_path, goal, mode, target
):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "year": 2024}
    bodies["/undated"] = (200, json.dumps([raw]).encode())
    bodies["/dated"] = (200, json.dumps([raw]).encode())
    output = tmp_path / "rows.json"
    result = await arun(
        goal=goal,
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/undated", "format": "json", "projection": years.undated_plan()},
            {"url": base + "/dated", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=1,
        max_steps=1,
        export=output,
        config=config,
    )
    assert not result.completed and result.dataset_consistency["gaps"] == [
        "/population:missing_reference_period"
    ]
    repairs = result.dataset_consistency["repairs"]
    assert len(repairs) == int(mode is not None)
    if repairs:
        assert repairs[0]["target_mode"] == mode and repairs[0]["target_year"] == target
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    assert manifest["dataset_consistency"] == result.dataset_consistency
    bodies.pop("/undated")
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.completed and resumed.dataset_consistency["repairs"] == []
    assert seen == ["/undated", "/dated"]


@pytest.mark.asyncio
async def test_latest_mixed_vintage_repair_identifies_only_older_record(site):
    base, bodies, _, config = site
    raw = temporal.rows()[0]
    bodies["/mixed"] = (
        200,
        json.dumps(
            [{**raw, "name": "Old", "year": 2024}, {**raw, "name": "New", "year": 2025}]
        ).encode(),
    )
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/mixed", "format": "json", "projection": temporal.plan(True, True)}
        ],
        identity=["/name"],
        maxrows=2,
        config=config,
    )
    assert not result.completed
    assert result.dataset_consistency["gaps"] == ["/population:mixed_reference_periods"]
    repairs = result.dataset_consistency["repairs"]
    assert len(repairs) == 1 and repairs[0]["reason"] == "stale_reference_period"
    assert repairs[0]["observed_year"] == 2024 and repairs[0]["target_year"] == 2025
    store = ResearchStore(config.sqlite_db_path)
    try:
        old = next(
            row
            for row in store.evidence(result.run_id)
            if row["candidate"]["record"]["name"] == "Old"
        )
        assert repairs[0]["record_id"] == old["record_id"]
        assert repairs[0]["snapshot_id"] == old["snapshot"]["id"]
    finally:
        store.close()
