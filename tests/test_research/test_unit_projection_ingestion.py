# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Unit plans require raw unit evidence and feed canonical completion and lineage."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from verboisy import arun
from verboisy.core.source_assessment import source_fitness_candidate_key
from verboisy.core.units import CanonicalUnit, unit_normalization_event
from verboisy.evidence.models import Candidate, ProjectionPlan, Snapshot, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.extractor.ingestion import row_evidence
from verboisy.extractor.unit_projection import grounded_projected_units
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work
PLAN = {
    "fields": [
        {"source": "/name", "target": "/name"},
        {
            "source": "/amount",
            "target": "/population",
            "conversion": "unit_base",
            "unit_source": "/unit",
        },
    ]
}
SCHEMA = fixtures.schema(
    {
        "name": {"type": "string"},
        "population": {
            "type": "integer",
            "x-verboisy-unit-sensitive": True,
            "x-verboisy-comparable-across-rows": True,
        },
    }
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["csv", "json", "jsonl"])
async def test_unit_plan_canonical_completion_lineage_and_offline_resume(site, tmp_path, fmt):
    base, bodies, seen, config = site
    rows = [
        {"name": "Anaïs", "amount": "2", "unit": "thousand persons"},
        {"name": "李雷", "amount": "2500", "unit": "people"},
    ]
    body = (
        "name,amount,unit\r\nAnaïs,2,thousand persons\r\n李雷,2500,people\r\n".encode()
        if fmt == "csv"
        else (
            json.dumps(rows, ensure_ascii=False).encode()
            if fmt == "json"
            else ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
        )
    )
    bodies["/people"] = (200, body)
    output = tmp_path / "people.json"
    result = await arun(
        goal="People",
        schema=SCHEMA,
        dataset_sources=[
            {
                "url": base + "/people",
                "format": fmt,
                "projection": PLAN,
            }
        ],
        identity=["/name"],
        maxrows=2,
        export=output,
        proof=True,
        config=config,
    )
    assert result.completed
    assert result.records == [
        {"id": 1, "name": "Anaïs", "population": 2000},
        {"id": 2, "name": "李雷", "population": 2500},
    ]
    manifest_path = output.with_suffix(".json.manifest.json")
    manifest = json.loads(manifest_path.read_text())
    cells = [cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population"]
    assert [cell["unit_derivation"]["row_index"] for cell in cells] == [1, 2]
    assert cells[0]["unit_derivation"]["unit_pointer"] == "/unit"
    assert cells[0]["unit_derivation"]["observed_unit_label"] == "thousand persons"
    assert cells[0]["unit_derivation"]["canonical_unit"] == {
        "dimension": "count",
        "base_unit": "person",
        "multiplier": 1,
    }
    assert cells[0]["unit_derivation"]["source_value_json"] == '"2"'
    assert all(cell["status"] == "resolved" for cell in cells)
    assets = load_portable_assets(manifest_path)
    assert assets[0].download.dataset.original_bytes == body
    assert (
        cells[1]["unit_derivation"]["line_start"] == assets[0].download.dataset.rows[1].line_start
    )
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.events(result.run_id, "unit_normalization") == []
        evidence = store.evidence(result.run_id)[0]
        assert evidence["candidate"]["evidence"]["/population"]["quote"] == '"2"'
        candidate = Candidate.model_validate(evidence["candidate"])
        page = Snapshot.model_validate(evidence["snapshot"])
        assert grounded_projected_units(candidate, page)["/population"].value == 2000
        summary = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, export=output, config=config)
    assert resumed.records == result.records and seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unit,gap", [("kg", "incompatible_units"), ("unknown", "dataset_row_gaps")]
)
async def test_unit_gap_never_becomes_completion(site, unit, gap):
    base, bodies, _, config = site
    rows = [
        {"name": "A", "amount": "2", "unit": "thousand persons"},
        {"name": "B", "amount": "2", "unit": unit},
    ]
    bodies["/people"] = (200, json.dumps(rows).encode())
    result = await arun(
        goal="People",
        schema=SCHEMA,
        dataset_sources=[
            {
                "url": base + "/people",
                "format": "json",
                "projection": PLAN,
            }
        ],
        maxrows=2,
        config=config,
    )
    assert not result.completed and result.status == "PAUSED"
    if unit == "unknown":
        assert result.stop_reason == gap
    else:
        store = ResearchStore(config.sqlite_db_path)
        assert any(
            any(gap in item for item in event["payload"].get("gaps", []))
            for event in store.events(result.run_id, "dataset_consistency_gap")
        )
        store.close()


@pytest.fixture
def context(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    rid = store.create("units", SCHEMA, TaskSpec(), None)
    aid = store.save_dataset_asset(
        rid, capture(b'[{"name":"A","amount":2,"unit":"thousand persons"}]', "json")
    )
    asset = store.load_dataset_asset(rid, aid)
    page, candidate = row_evidence(
        asset, asset.download.dataset.rows[0], ProjectionPlan.model_validate(PLAN)
    )
    try:
        yield store, rid, page, candidate
    finally:
        store.close()


@pytest.mark.parametrize(
    "change",
    [
        "label_source",
        "missing_source",
        "source_scope",
        "raw_alias",
        "candidate",
        "scope",
        "asset",
        "row",
        "raw",
        "bad_raw",
    ],
)
def test_unit_evidence_independent_replay_rejects_mutations(context, change):
    _, _, page, candidate = context
    assert verify(candidate, page, SCHEMA, TaskSpec()) == []
    assert grounded_projected_units(candidate, page)
    if change == "label_source":
        next(source for source in page.sources if source.id == "/unit").text = '"people"'
    if change == "missing_source":
        page.sources = [source for source in page.sources if source.id != "/unit"]
    if change == "source_scope":
        next(source for source in page.sources if source.id == "/unit").scope = "foreign"
    if change == "raw_alias":
        page.dataset_source_row_json = page.dataset_source_row_json.replace(
            "thousand persons", "thousand people"
        )
    if change == "candidate":
        candidate.record["population"] = 2000000
    if change == "scope":
        candidate.scope = "foreign"
    if change == "asset":
        page.dataset_asset_id = None
    if change == "row":
        page.dataset_row_index = None
    if change == "raw":
        page.dataset_source_row_json = None
    if change == "bad_raw":
        page.dataset_source_row_json = "not json"
    assert not grounded_projected_units(candidate, page)
    assert verify(candidate, page, SCHEMA, TaskSpec())


def test_unit_model_requires_explicit_auxiliary_column_and_keeps_legacy_json():
    old = ProjectionPlan.model_validate({"fields": [{"source": "/a", "target": "/b"}]})
    assert old.model_dump() == {
        "version": "1",
        "fields": [{"source": "/a", "target": "/b", "conversion": "identity"}],
    }
    for declaration in [
        {"source": "/a", "target": "/b", "conversion": "unit_base"},
        {"source": "/a", "target": "/b", "unit_source": "/unit"},
        {"source": "/a", "target": "/b", "conversion": "integer", "unit_source": "/unit"},
    ]:
        with pytest.raises(ValidationError):
            ProjectionPlan.model_validate({"fields": [declaration]})


def test_unit_projection_cannot_be_normalized_again_by_legacy_event(context):
    store, rid, page, candidate = context
    store.queue(rid, page.url, 0, None)
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], page, "fixture")
    outcome = store.accept(rid, page, candidate, [], TaskSpec())
    record_id = str(store.records(rid)[0]["id"])
    assert outcome == "accepted"
    event = unit_normalization_event(
        record_id=record_id,
        pointer="/population",
        original_value=2000,
        unit=CanonicalUnit("count", "person", 1000),
        candidate_key=source_fitness_candidate_key(candidate),
        snapshot_id=page.id,
    )
    store.event(rid, "unit_normalization", event)
    claims = {"/population": SimpleNamespace(unit=SimpleNamespace(label="thousand persons"))}
    with patch("verboisy.storage.research.claim_comparability_from_events", return_value=claims):
        assert store.records(rid)[0]["population"] == 2000
