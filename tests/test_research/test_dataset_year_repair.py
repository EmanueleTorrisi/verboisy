# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Grounded required reference years repair repeated dataset identities."""

import json

import pytest
from verboisy import arun
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_temporal_projection_ingestion as temporal

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


def undated_plan():
    plan = temporal.plan(True, True)
    plan["fields"][1].pop("reference_year_source")
    return plan


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal,year",
    [
        ("Latest population", 2025),
        ("Population in 2024", 2024),
        ("Population from 2023 to 2025", 2024),
    ],
)
async def test_year_only_repair_preserves_identity_and_exports_grounded_lineage(
    site, tmp_path, goal, year
):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "year": year}
    bodies["/undated"] = (200, json.dumps([raw]).encode())
    bodies["/dated"] = (200, json.dumps([raw]).encode())
    output = tmp_path / "rows.json"
    result = await arun(
        goal=goal,
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/undated", "format": "json", "projection": undated_plan()},
            {"url": base + "/dated", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=1,
        export=output,
        config=config,
    )
    assert result.completed and len(result.records) == 1
    assert result.records[0]["population"] == 2000
    store = ResearchStore(config.sqlite_db_path)
    try:
        evidence = store.evidence(result.run_id)[0]
        assert evidence["candidate"]["temporal_evidence"]["/population"]["reference_year"] == year
        superseded = store.events(result.run_id, "candidate_superseded")
        assert (
            len(superseded) == 1 and superseded[0]["payload"]["stable_id"] == evidence["record_id"]
        )
        comparison = store.events(result.run_id, "candidate_comparison")[-1]["payload"]
        assert comparison["comparison_mode"] == "dataset_metadata_repair"
        assert comparison["preference"] == "new" and comparison["changed_fields"] == []
        summary = store.summary(result.run_id)
    finally:
        store.close()
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population")
    assert cell["status"] == "resolved" and cell["temporal_derivation"]["reference_year"] == year
    assert "unit_derivation" in cell and "descriptor_derivations" in cell
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records and seen == ["/undated", "/dated"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.parametrize(
    "case",
    [
        "required",
        "preferred",
        "not_comparable",
        "static",
        "future",
        "wrong_period",
        "invalid_quote",
        "changed_value",
        "changed_definition",
    ],
)
def test_year_repair_policy_and_preservation_guards(tmp_path, case):
    from verboisy.core.planner import TemporalIntent
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import ProjectionPlan, TaskSpec
    from verboisy.extractor.ingestion import _dataset_preference, row_evidence
    from verboisy.utils.config import Settings

    from tests.test_storage.test_dataset_assets import capture

    schema = temporal.schema(True, True)
    field = schema["properties"]["population"]
    if case == "preferred":
        field["x-verboisy-reference-period"] = "preferred"
    if case == "not_comparable":
        field["x-verboisy-comparable-across-rows"] = False
    if case == "static":
        field["x-verboisy-temporal-class"] = "static"
    store = ResearchStore(str(tmp_path / "run.db"))
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("Latest population", schema, task, None)

    def make(plan, updates=None):
        raw = {**temporal.rows()[0], **(updates or {})}
        aid = store.save_dataset_asset(rid, capture(json.dumps([raw]).encode(), "json"))
        asset = store.load_dataset_asset(rid, aid)
        page, candidate = row_evidence(
            asset, asset.download.dataset.rows[0], ProjectionPlan.model_validate(plan)
        )
        store.queue(rid, page.url, 0, None)
        work = store.db.execute(
            "SELECT id FROM pages WHERE run_id=? AND url=?", (rid, page.url)
        ).fetchone()
        if store.load_snapshot(rid, page.id) is None:
            store.snapshot(rid, work[0], page, "fixture")
        return page, candidate

    try:
        old_page, old = make(undated_plan())
        assert store.accept(rid, old_page, old, [], task) == "accepted"
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        updates = {}
        if case == "future":
            updates["year"] = runner.current_year + 1
        if case == "wrong_period":
            runner.temporal_intent = TemporalIntent(mode="year", start_year=2024)
        if case == "changed_value":
            updates["amount"] = "3"
        if case == "changed_definition":
            updates["definition"] = "Different population"
        page, candidate = make(temporal.plan(True, True), updates)
        if case == "invalid_quote":
            candidate.temporal_evidence["/population"].quote = '"invented"'
        expected = (
            "new" if case == "required" else "conflict" if case == "changed_value" else "same"
        )
        assert _dataset_preference(runner, page, candidate) == expected
        assert store.evidence(rid)[0]["candidate"]["temporal_evidence"] == {}
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("goal,year", [("Latest population", 9999), ("Population in 2024", 2025)])
async def test_invalid_period_keeps_missing_year_gap(site, goal, year):
    base, bodies, seen, config = site
    raw = temporal.rows()[0]
    bodies["/undated"] = (200, json.dumps([raw]).encode())
    bodies["/dated"] = (200, json.dumps([{**raw, "year": year}]).encode())
    result = await arun(
        goal=goal,
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/undated", "format": "json", "projection": undated_plan()},
            {"url": base + "/dated", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=1,
        config=config,
    )
    assert not result.completed and result.stop_reason == "dataset_consistency_gaps"
    assert len(result.records) == 1 and seen == ["/undated", "/dated"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.evidence(result.run_id)[0]["candidate"]["temporal_evidence"] == {}
        assert store.events(result.run_id, "candidate_superseded") == []
    finally:
        store.close()
