# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Dataset refresh uses declared identities and latest policy without counting updates twice."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.core.planner import TemporalIntent
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first,second,value", [(2024, 2025, "2"), (2025, 2024, "3"), (2024, 2025, "3")]
)
async def test_latest_refresh_preserves_stable_identity_and_entity_target(
    site, tmp_path, first, second, value
):
    base, bodies, seen, config = site
    seed = temporal.rows()[0]
    rows = [
        {**seed, "name": "A", "year": first},
        {**seed, "name": "A", "year": second, "amount": value},
        {**seed, "name": "B", "year": 2025},
    ]
    bodies["/people"] = (200, json.dumps(rows).encode())
    output = tmp_path / "people.json"
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/people", "format": "json", "projection": temporal.plan(True, True)}
        ],
        identity=["/name"],
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed and len(result.records) == 2
    assert [row["name"] for row in result.records] == ["A", "B"]
    assert result.records[0]["population"] == (int(value) * 1000 if second > first else 2000)
    store = ResearchStore(config.sqlite_db_path)
    try:
        evidence = store.evidence(result.run_id)
        accepted = next(row for row in evidence if row["candidate"]["record"]["name"] == "A")
        assert accepted["candidate"]["temporal_evidence"]["/population"]["reference_year"] == 2025
        events = store.events(result.run_id, "candidate_superseded")
        if second > first:
            assert len(events) == 1 and events[0]["payload"]["stable_id"] == accepted["record_id"]
        else:
            assert events == []
        assert len(store.events(result.run_id, "dataset_row")) == 3
        assert store.events(result.run_id, "candidate_comparison")[-1]["payload"]["preference"] == (
            "new" if second > first else "old"
        )
        summary = store.summary(result.run_id)
    finally:
        store.close()
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population")
    assert cell["temporal_derivation"]["reference_year"] == 2025
    assert cell["temporal_derivation"]["row_index"] == (2 if second > first else 1)
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records and seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.fixture
def context(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("Latest population", temporal.schema(True, True), task, None)

    def candidate(year, declarations=None, updates=None):
        raw = {**temporal.rows()[0], "year": year, **(updates or {})}
        aid = store.save_dataset_asset(rid, capture(json.dumps([raw]).encode(), "json"))
        asset = store.load_dataset_asset(rid, aid)
        page, value = row_evidence(
            asset,
            asset.download.dataset.rows[0],
            ProjectionPlan.model_validate(declarations or temporal.plan(True, True)),
        )
        store.queue(rid, page.url, 0, None)
        work = store.db.execute(
            "SELECT id FROM pages WHERE run_id=? AND url=?", (rid, page.url)
        ).fetchone()
        if store.load_snapshot(rid, page.id) is None:
            store.snapshot(rid, work[0], page, "fixture")
        return page, value

    old_page, old = candidate(2024)
    assert store.accept(rid, old_page, old, [], task) == "accepted"
    runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
    try:
        yield store, rid, runner, candidate, old_page, old
    finally:
        store.close()


@pytest.mark.parametrize(
    "case",
    [
        "unit_missing",
        "unit_changed",
        "definition_missing",
        "definition_changed",
        "methodology_changed",
    ],
)
def test_newer_year_cannot_discard_or_change_grounded_metadata(context, case):
    store, rid, runner, make, _, _ = context
    supplied = temporal.plan(True, True)
    updates = {}
    if case == "unit_missing":
        supplied["fields"][1].pop("unit_source")
        supplied["fields"][1]["conversion"] = "integer"
        updates["amount"] = "2000"
    if case == "unit_changed":
        updates["unit"] = "kg"
    if case == "definition_missing":
        supplied["fields"][1]["descriptors"] = [{"kind": "methodology", "source": "/methodology"}]
    if case == "definition_changed":
        updates["definition"] = "Other population"
    if case == "methodology_changed":
        updates["methodology"] = "Other method"
    page, candidate = make(2025, supplied, updates)
    previous = store.records(rid)
    assert _dataset_preference(runner, page, candidate) == "old"
    assert (
        store.events(rid, "candidate_comparison")[-1]["payload"]["blocked_reason"]
        == "metadata_regression"
    )
    store.accept(rid, page, candidate, [], runner.task, preference="old")
    assert store.records(rid) == previous


@pytest.mark.parametrize(
    "case", ["missing_snapshot", "invalid_old", "no_previous", "same_period", "unknown_semantics"]
)
def test_unavailable_or_unordered_evidence_is_not_promoted(context, case):
    store, rid, runner, make, _, _ = context
    page, candidate = make(2024 if case == "same_period" else 2025)
    if case == "unknown_semantics":
        runner.field_semantics = {}
    if case == "no_previous":
        candidate.record["name"] = "Other"
    with (
        patch.object(store, "load_snapshot", return_value=None)
        if case == "missing_snapshot"
        else patch(
            "verboisy.extractor.ingestion.verify",
            return_value=["invalid"] if case == "invalid_old" else [],
        )
    ):
        preference = _dataset_preference(runner, page, candidate)
    assert preference == (
        None
        if case == "no_previous"
        else "old"
        if case in {"missing_snapshot", "invalid_old"}
        else "same"
    )


def test_temporal_metadata_on_other_fields_cannot_be_dropped_or_changed(context):
    store, rid, runner, make, _, _ = context
    supplied = temporal.plan(True, True)
    supplied["fields"][0]["reference_year_source"] = "/year"
    old_page, old = make(2024, supplied)
    assert store.accept(rid, old_page, old, [], runner.task, preference="new") == "accepted"
    page, candidate = make(2025)
    assert _dataset_preference(runner, page, candidate) == "old"

    page, candidate = make(2025, supplied)
    assert _dataset_preference(runner, page, candidate) == "old"


@pytest.mark.parametrize("temporal_class", ["event", "time_series"])
def test_historical_row_classes_are_not_given_implicit_latest_replacement(context, temporal_class):
    _, _, runner, make, _, _ = context
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"], temporal_class=temporal_class
    )
    page, candidate = make(2025)
    assert _dataset_preference(runner, page, candidate) == "same"


def test_explicit_field_intent_and_same_period_conflicts(context):
    _, _, runner, make, _, _ = context
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"], temporal_intent=TemporalIntent(mode="latest")
    )
    page, candidate = make(2024, updates={"amount": "3"})
    assert _dataset_preference(runner, page, candidate) == "conflict"
