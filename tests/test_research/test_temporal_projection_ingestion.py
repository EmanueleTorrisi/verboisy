# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared reference-year sources produce independently replayed temporal proofs."""

import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli.main import app
from verboisy.evidence.models import ProjectionPlan, TaskSpec, TemporalProof
from verboisy.evidence.verify import verify
from verboisy.extractor.ingestion import row_evidence
from verboisy.extractor.projection import ProjectionError, project_row
from verboisy.extractor.temporal_projection import grounded_projected_years
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_descriptor_projection_ingestion as descriptors
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


def plan(unit=False, described=False):
    result = descriptors.plan(unit=unit)
    field = result["fields"][1]
    if not described:
        del field["descriptors"]
    field["reference_year_source"] = "/year"
    return result


def schema(unit=False, described=False, temporal_class="mutable"):
    result = descriptors.schema(kinds=("definition", "methodology") if described else (), unit=unit)
    field = result["properties"]["population"]
    field["x-verboisy-temporal-class"] = temporal_class
    field["x-verboisy-reference-period"] = "required"
    return result


def rows():
    return [{**row, "year": "2025"} for row in descriptors.rows()]


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["csv", "json", "jsonl"])
@pytest.mark.parametrize(
    "unit,described", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_temporal_completion_lineage_metadata_composition_and_offline_resume(
    site, tmp_path, fmt, unit, described
):
    base, bodies, seen, config = site
    source = rows()
    body = (
        (
            "name,amount,unit,definition,methodology,year\r\n"
            "Anaïs,2,thousand persons,通常人口,Census 2025,2025\r\n"
            "李雷,2,thousand persons,通常人口,Census 2025,2025\r\n"
        ).encode()
        if fmt == "csv"
        else (
            json.dumps(source, ensure_ascii=False).encode()
            if fmt == "json"
            else ("\n".join(json.dumps(row, ensure_ascii=False) for row in source) + "\n").encode()
        )
    )
    bodies["/people"] = (200, body)
    output = tmp_path / "people.json"
    result = await arun(
        goal="Population in 2025",
        schema=schema(unit, described),
        dataset_sources=[
            {"url": base + "/people", "format": fmt, "projection": plan(unit, described)}
        ],
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed
    assert [row["population"] for row in result.records] == [2000 if unit else 2] * 2
    manifest_path = output.with_suffix(".json.manifest.json")
    manifest = json.loads(manifest_path.read_text())
    cells = [cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population"]
    assets = load_portable_assets(manifest_path)
    assert assets[0].download.dataset.original_bytes == body
    for index, cell in enumerate(cells):
        year = cell["temporal_derivation"]
        assert cell["status"] == "resolved" and year["reference_year"] == 2025
        assert year["observed_year_json"] == '"2025"' and year["source_value_json"] == '"2"'
        assert year["year_pointer"] == "/year" and year["row_index"] == index + 1
        assert year["line_start"] == assets[0].download.dataset.rows[index].line_start
        assert ("unit_derivation" in cell) is unit
        assert ("descriptor_derivations" in cell) is described
    store = ResearchStore(config.sqlite_db_path)
    try:
        before = store.summary(result.run_id)
        proof = store.evidence(result.run_id)[0]["candidate"]["temporal_evidence"]["/population"]
        assert proof == {"source": "/year", "quote": '"2025"', "reference_year": 2025}
        assert not store.events(result.run_id, "source_fitness")
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config, export=output)
    assert resumed.records == result.records and seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == before
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "year,goal,reason",
    [
        ("2024", "Population in 2025", "temporal_mismatch"),
        ("9999", "Latest population", "future_temporal_value"),
        (None, "Population in 2025", "invalid_projection"),
    ],
)
async def test_mismatched_future_or_missing_years_do_not_count_as_completion(
    site, year, goal, reason
):
    base, bodies, _, config = site
    source = rows()
    source[1]["year"] = year
    bodies["/people"] = (200, json.dumps(source).encode())
    result = await arun(
        goal=goal,
        schema=schema(),
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": plan()}],
        maxrows=2,
        config=config,
    )
    assert not result.completed and result.status == "PAUSED" and len(result.records) == 1
    store = ResearchStore(config.sqlite_db_path)
    try:
        events = store.events(result.run_id)
        assert any(reason in json.dumps(event["payload"]) for event in events)
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("temporal_class,completed", [("mutable", False), ("time_series", True)])
async def test_mixed_reference_years_respect_snapshot_and_series_policy(
    site, temporal_class, completed
):
    base, bodies, _, config = site
    source = rows()
    source[0]["year"] = 2024
    bodies["/people"] = (200, json.dumps(source).encode())
    result = await arun(
        goal="Population from 2024 to 2025",
        schema=schema(temporal_class=temporal_class),
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": plan()}],
        maxrows=2,
        config=config,
    )
    assert result.completed is completed and len(result.records) == 2
    if not completed:
        assert result.stop_reason == "dataset_consistency_gaps"


@pytest.fixture
def context(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    rid = store.create("Population in 2025", schema(), TaskSpec(), None)
    aid = store.save_dataset_asset(rid, capture(json.dumps(rows()).encode(), "json"))
    asset = store.load_dataset_asset(rid, aid)
    page, candidate = row_evidence(
        asset, asset.download.dataset.rows[0], ProjectionPlan.model_validate(plan())
    )
    try:
        yield store, rid, page, candidate
    finally:
        store.close()


@pytest.mark.parametrize(
    "change",
    [
        "source_text",
        "missing_source",
        "source_scope",
        "source_kind",
        "missing_proof",
        "proof_source",
        "proof_quote",
        "proof_year",
        "raw_year",
        "candidate",
        "candidate_scope",
        "asset",
        "row",
        "raw",
        "bad_raw",
    ],
)
def test_year_source_and_temporal_proof_are_independently_verified(context, change):
    _, _, page, candidate = context
    assert verify(candidate, page, schema(), TaskSpec()) == []
    assert grounded_projected_years(candidate, page)
    source = next(source for source in page.sources if source.id == "/year")
    proof = candidate.temporal_evidence["/population"]
    if change == "source_text":
        source.text = '"2024"'
    if change == "missing_source":
        page.sources.remove(source)
    if change == "source_scope":
        source.scope = "page"
    if change == "source_kind":
        source.kind = "link"
    if change == "missing_proof":
        candidate.temporal_evidence.clear()
    if change == "proof_source":
        proof.source = "/name"
    if change == "proof_quote":
        proof.quote = "2025"
    if change == "proof_year":
        proof.reference_year = 2024
    if change == "raw_year":
        page.dataset_source_row_json = page.dataset_source_row_json.replace("2025", "2024")
    if change == "candidate":
        candidate.record["population"] = 9
    if change == "candidate_scope":
        candidate.scope = "foreign"
    if change == "asset":
        page.dataset_asset_id = None
    if change == "row":
        page.dataset_row_index = None
    if change == "raw":
        page.dataset_source_row_json = None
    if change == "bad_raw":
        page.dataset_source_row_json = "not json"
    assert not grounded_projected_years(candidate, page)
    assert verify(candidate, page, schema(), TaskSpec())


def test_undeclared_temporal_proofs_and_container_year_bindings_are_rejected(context):
    _, _, page, candidate = context
    candidate.temporal_evidence["/name"] = TemporalProof(
        source="/year", quote='"2025"', reference_year=2025
    )
    assert verify(candidate, page, schema(), TaskSpec()) == [
        "dataset_temporal_projection_not_grounded"
    ]
    source = capture(b'[{"name":"A","amount":[2],"year":2025}]', "json").dataset.rows[0]
    declared = plan()
    declared["fields"][1]["conversion"] = "identity"
    with pytest.raises(ProjectionError, match="scalar target"):
        project_row(source, ProjectionPlan.model_validate(declared))


def test_legacy_plan_serialization_and_strict_year_source_declarations():
    declared = descriptors.plan(unit=True)
    assert (
        "reference_year_source"
        not in ProjectionPlan.model_validate(declared).model_dump()["fields"][1]
    )
    for year_source in [None, 2025, ""]:
        supplied = plan()
        supplied["fields"][1]["reference_year_source"] = year_source
        with pytest.raises(ValidationError):
            ProjectionPlan.model_validate(supplied)


@pytest.mark.asyncio
async def test_cli_approved_year_binding_and_grouped_contributor_lineage(site, tmp_path):
    base, bodies, seen, config = site
    bodies["/people"] = (200, json.dumps(rows()).encode())
    sources = [{"url": base + "/people", "format": "json"}]
    original = await arun(
        goal="Population in 2025",
        schema=schema(True, True),
        dataset_sources=sources,
        maxrows=2,
        config=config,
    )
    assert not original.records
    store = ResearchStore(config.sqlite_db_path)
    aid = store.dataset_assets(original.run_id)[0].id
    store.close()
    supplied, report, approved = (
        tmp_path / name for name in ("supplied.json", "review.json", "approved.json")
    )
    supplied.write_text(json.dumps(plan(True, True)))
    result = CliRunner().invoke(
        app,
        [
            "map",
            "--database",
            config.sqlite_db_path,
            "--run-id",
            original.run_id,
            "--asset-id",
            aid,
            "--projection",
            str(supplied),
            "--output",
            str(report),
            "--plan",
            str(approved),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(report.read_text())["suggestion"]["unmapped_profile_pointers"] == []
    output = tmp_path / "group.json"
    accepted = await arun(
        goal="Population in 2025",
        schema=schema(True, True),
        dataset_sources=sources,
        dataset_projection=approved,
        groupby="population",
        maxrows=2,
        export=output,
        config=config,
    )
    assert accepted.completed and len(accepted.records) == 1 and seen == ["/people", "/people"]
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population")
    assert cell["status"] == "resolved" and [
        source["temporal_derivation"]["row_index"] for source in cell["contributors"]
    ] == [1, 2]
