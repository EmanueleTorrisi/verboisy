# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""An entity target bounds new identities while declared rows can repair existing ones."""

import json

import pytest
from verboisy import arun
from verboisy.evidence.models import ProjectionPlan
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_dataset_metadata_refresh as metadata
from tests.test_research import test_temporal_projection_ingestion as temporal

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unit", "definition", "methodology"])
@pytest.mark.parametrize("same_asset", [False, True])
async def test_target_one_repairs_without_accepting_extra_entities(
    site, tmp_path, kind, same_asset
):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons"}
    rows = [raw, {**raw, "name": "Unrelated"}]
    bodies["/first"] = (200, json.dumps(rows).encode())
    bodies["/repair"] = (200, json.dumps([rows[1], raw]).encode())
    repair_path = "/first" if same_asset else "/repair"
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {"url": base + "/first", "format": "json", "projection": metadata.missing_plan(kind)},
            {"url": base + repair_path, "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=1,
        export=tmp_path / "rows.json",
        config=config,
    )
    assert result.completed and len(result.records) == 1
    assert result.records[0]["name"] == raw["name"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(result.run_id, "candidate_superseded")) == 1
        evidence = store.evidence(result.run_id)[0]
        assert (
            evidence["snapshot"]["dataset_projection"]
            == ProjectionPlan.model_validate(temporal.plan(True, True)).model_dump()
        )
        assert (
            store.events(result.run_id, "candidate_superseded")[0]["payload"]["stable_id"]
            == evidence["record_id"]
        )
        skipped = [
            event
            for event in store.events(result.run_id, "dataset_row")
            if event["payload"]["outcome"] == "skipped"
        ]
        assert len(skipped) == (1 if same_asset else 2)
        assert all(event["payload"]["reasons"] == ["entity_target_reached"] for event in skipped)
        summary = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records
    assert seen == (["/first"] if same_asset else ["/first", "/repair"])
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_available", [False, True])
async def test_repair_download_budget_and_paused_resume(site, repair_available):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons"}
    bodies["/first"] = (200, json.dumps([raw]).encode())
    bodies["/repair"] = (200, json.dumps([raw]).encode())
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {
                "url": base + "/first",
                "format": "json",
                "projection": metadata.missing_plan("definition"),
            },
            {
                "url": base + "/repair",
                "format": "json",
                "projection": temporal.plan(True, True)
                if repair_available
                else metadata.missing_plan("definition"),
            },
        ],
        identity=["/name"],
        maxrows=1,
        max_steps=1,
        config=config,
    )
    assert not result.completed and result.stop_reason == "dataset_source_budget"
    assert seen == ["/first"] and len(result.records) == 1
    store = ResearchStore(config.sqlite_db_path)
    try:
        previous = store.evidence(result.run_id)[0]["record_id"]
    finally:
        store.close()
    bodies.pop("/first")
    resumed = await arun(resume=result.run_id, max_steps=1, config=config)
    assert resumed.completed is repair_available
    assert len(resumed.records) == 1 and seen == ["/first", "/repair"]
    if not repair_available:
        assert resumed.stop_reason == "dataset_consistency_gaps"
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.evidence(result.run_id)[0]["record_id"] == previous
        summary = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    again = await arun(resume=result.run_id, config=config)
    assert again.records == resumed.records and again.completed == resumed.completed
    assert seen == ["/first", "/repair"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,complete", [(False, False), (True, True)])
async def test_target_stops_without_identity_or_remaining_metadata_gap(site, identity, complete):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons"}
    bodies["/first"] = (200, json.dumps([raw]).encode())
    bodies["/unused"] = (200, json.dumps([raw]).encode())
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {
                "url": base + "/first",
                "format": "json",
                "projection": temporal.plan(True, True)
                if complete
                else metadata.missing_plan("definition"),
            },
            {"url": base + "/unused", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"] if identity else None,
        maxrows=1,
        config=config,
    )
    assert result.completed is complete and len(result.records) == 1
    assert seen == ["/first"]
