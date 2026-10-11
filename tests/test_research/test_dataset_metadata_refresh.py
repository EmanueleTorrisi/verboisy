# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Required grounded metadata repairs preserve accepted dataset identity."""

import json

import pytest
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.extractor.ingestion import _dataset_preference, row_evidence
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_temporal_projection_ingestion as temporal
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


def missing_plan(kind):
    plan = temporal.plan(True, True)
    field = plan["fields"][1]
    if kind == "unit":
        field.pop("unit_source")
        field["conversion"] = "integer"
    else:
        field["descriptors"] = [
            binding for binding in field["descriptors"] if binding["kind"] != kind
        ]
    return plan


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unit", "definition", "methodology"])
async def test_repair_completion_lineage_and_resume(site, tmp_path, kind):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons"}
    bodies["/first"] = (200, json.dumps([raw]).encode())
    bodies["/repair"] = (200, json.dumps([raw, {**raw, "name": "Other"}]).encode())
    output = tmp_path / "people.json"
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/first", "format": "json", "projection": missing_plan(kind)},
            {"url": base + "/repair", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed and len(result.records) == 2
    store = ResearchStore(config.sqlite_db_path)
    try:
        events = store.events(result.run_id, "candidate_superseded")
        assert len(events) == 1
        evidence = store.evidence(result.run_id)
        assert events[0]["payload"]["stable_id"] == evidence[0]["record_id"]
        assert evidence[0]["snapshot"]["url"].endswith("/repair")
        assert (
            store.events(result.run_id, "candidate_comparison")[-1]["payload"]["comparison_mode"]
            == "dataset_metadata_repair"
        )
        assert len(store.events(result.run_id, "dataset_row")) == 3
        summary = store.summary(result.run_id)
    finally:
        store.close()
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population")
    assert cell["status"] == "resolved" and cell["temporal_derivation"]["reference_year"] == 2025
    assert "unit_derivation" in cell and "descriptor_derivations" in cell
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records and seen == ["/first", "/repair"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.parametrize(
    "case",
    [
        "repair",
        "insensitive",
        "no_semantics",
        "value_changed",
        "temporal_lost",
        "unit_lost",
        "descriptor_changed",
        "invalid_new",
        "typed_difference",
    ],
)
def test_repair_guards(tmp_path, case):
    store = ResearchStore(str(tmp_path / "run.db"))
    schema = temporal.schema(True, True)
    if case == "insensitive":
        schema["properties"]["population"]["x-verboisy-definition-sensitive"] = False
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("Latest population", schema, task, None)

    def make(plan, updates=None):
        raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons", **(updates or {})}
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
        old_page, old = make(missing_plan("definition"))
        assert store.accept(rid, old_page, old, [], task) == "accepted"
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        plan = temporal.plan(True, True)
        updates = {}
        if case == "no_semantics":
            runner.field_semantics = {}
        if case == "value_changed":
            updates["amount"] = "3000"
        if case == "temporal_lost":
            plan["fields"][1].pop("reference_year_source")
        if case == "unit_lost":
            plan["fields"][1].pop("unit_source")
            plan["fields"][1]["conversion"] = "integer"
        if case == "descriptor_changed":
            updates["methodology"] = "Other method"
        page, candidate = make(plan, updates)
        if case == "invalid_new":
            candidate.evidence["/population"].quote = '"invented"'
        if case == "typed_difference":
            candidate.record["population"] = 2000.0
        expected = "new" if case == "repair" else "conflict" if case == "value_changed" else "same"
        assert _dataset_preference(runner, page, candidate) == expected
        if case == "repair":
            previous = store.evidence(rid)[0]["record_id"]
            assert store.accept(rid, page, candidate, [], task, preference="new") == "accepted"
            assert store.evidence(rid)[0]["record_id"] == previous
            assert len(store.records(rid)) == 1
    finally:
        store.close()
