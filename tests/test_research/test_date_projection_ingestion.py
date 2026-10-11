# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared dates replay from immutable raw file evidence through export and resume."""

import json

import pytest
from verboisy import arun
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.extractor.ingestion import row_evidence
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work
SCHEMA = fixtures.schema({"name": {"type": "string"}, "date": {"type": "string", "format": "date"}})


def plan(mode):
    return {
        "fields": [
            {"source": "/name", "target": "/name"},
            {"source": "/observed", "target": "/date", "conversion": mode},
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt,mode,value",
    [
        ("csv", "date_dmy", "29/02/2024"),
        ("json", "date_mdy", "02/29/2024"),
        ("jsonl", "date_iso", "2024-02-29"),
    ],
)
async def test_declared_date_export_evidence_and_offline_resume(site, tmp_path, fmt, mode, value):
    base, bodies, seen, config = site
    row = {"name": "Anaïs", "observed": value}
    body = (
        f"name,observed\r\nAnaïs,{value}\r\n".encode()
        if fmt == "csv"
        else json.dumps([row] if fmt == "json" else row, ensure_ascii=False).encode()
    )
    bodies["/dates"] = (200, body)
    output = tmp_path / "dates.json"
    result = await arun(
        goal="Dates",
        schema=SCHEMA,
        dataset_sources=[
            {
                "url": base + "/dates",
                "format": fmt,
                "projection": plan(mode),
            }
        ],
        identity=["/name"],
        maxrows=1,
        export=output,
        proof=True,
        config=config,
    )
    assert result.completed
    assert result.records == [{"id": 1, "name": "Anaïs", "date": "29/02/2024"}]
    manifest_path = output.with_suffix(".json.manifest.json")
    manifest = json.loads(manifest_path.read_text())
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/date")
    assert cell["source_value"] == value and cell["source_pointer"] == "/observed"
    assert cell["output_value"] == "29/02/2024" and cell["status"] == "resolved"
    assert cell["raw_value"] == "2024-02-29"
    assert cell["steps"][-1]["operation"] == "presentation"
    assert cell["steps"][0]["plan"]["fields"][1]["conversion"] == mode
    assert load_portable_assets(manifest_path)[0].download.dataset.original_bytes == body
    store = ResearchStore(config.sqlite_db_path)
    try:
        evidence = store.evidence(result.run_id)[0]
        assert evidence["candidate"]["record"]["date"] == "2024-02-29"
        assert evidence["candidate"]["evidence"]["/date"]["quote"] == json.dumps(value)
        assert json.loads(evidence["snapshot"]["dataset_source_row_json"])["observed"] == value
        summary = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, export=output, config=config)
    assert resumed.records == result.records
    assert seen == ["/dates"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.asyncio
async def test_bad_calendar_row_is_retained_as_gap_and_resume_does_not_reinterpret(site):
    base, bodies, seen, config = site
    bodies["/dates"] = (
        200,
        b'[{"name":"A","observed":"29/02/2025"},{"name":"B","observed":"28/02/2025"}]',
    )
    first = await arun(
        goal="Dates",
        schema=SCHEMA,
        dataset_sources=[
            {
                "url": base + "/dates",
                "format": "json",
                "projection": plan("date_dmy"),
            }
        ],
        maxrows=2,
        config=config,
    )
    assert first.status == "PAUSED" and first.stop_reason == "dataset_row_gaps"
    assert first.records == [{"id": 1, "name": "B", "date": "28/02/2025"}]
    second = await arun(resume=first.run_id, config=config)
    assert second.records == first.records
    assert seen == ["/dates"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(first.run_id, "dataset_projection_failure")) == 1
        assert len(store.dataset_assets(first.run_id)[0].download.dataset.rows) == 2
    finally:
        store.close()


def test_date_proof_independent_replay_rejects_altered_value(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    try:
        rid = store.create("dates", SCHEMA, TaskSpec(), None)
        aid = store.save_dataset_asset(
            rid, capture(b'[{"name":"A","observed":"03/04/2025"}]', "json")
        )
        asset = store.load_dataset_asset(rid, aid)
        snapshot, candidate = row_evidence(
            asset, asset.download.dataset.rows[0], ProjectionPlan.model_validate(plan("date_dmy"))
        )
        assert verify(candidate, snapshot, SCHEMA, TaskSpec()) == []
        altered = candidate.model_copy(deep=True)
        altered.record["date"] = "2025-03-04"
        assert verify(altered, snapshot, SCHEMA, TaskSpec())
        altered_snapshot = snapshot.model_copy(deep=True)
        altered_snapshot.dataset_projection.fields[1].conversion = "date_mdy"
        assert verify(candidate, altered_snapshot, SCHEMA, TaskSpec())
    finally:
        store.close()
