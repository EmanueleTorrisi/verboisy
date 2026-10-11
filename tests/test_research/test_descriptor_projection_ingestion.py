# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared descriptors are replayed, required for comparability and portable."""

import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli.main import app
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.extractor.descriptor_projection import grounded_projected_descriptors
from verboisy.extractor.ingestion import row_evidence
from verboisy.extractor.projection import ProjectionError, project_row
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


def plan(kinds=("definition", "methodology"), unit=False):
    field = {"source": "/amount", "target": "/population", "conversion": "integer"}
    if unit:
        field.update(conversion="unit_base", unit_source="/unit")
    field["descriptors"] = [{"kind": kind, "source": "/" + kind} for kind in kinds]
    return {"fields": [{"source": "/name", "target": "/name"}, field]}


def schema(kinds=("definition", "methodology"), unit=False):
    field = {"type": "integer", "x-verboisy-comparable-across-rows": True}
    for kind in kinds:
        field["x-verboisy-" + kind + "-sensitive"] = True
    if unit:
        field["x-verboisy-unit-sensitive"] = True
    return fixtures.schema({"name": {"type": "string"}, "population": field})


def rows():
    return [
        {
            "name": name,
            "amount": "2",
            "unit": "thousand persons",
            "definition": "通常人口",
            "methodology": "Census 2025",
        }
        for name in ("Anaïs", "李雷")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["csv", "json", "jsonl"])
@pytest.mark.parametrize("unit", [False, True])
async def test_grounded_completion_portable_descriptors_and_offline_resume(
    site, tmp_path, fmt, unit
):
    base, bodies, seen, config = site
    source = rows()
    body = (
        (
            "name,amount,unit,definition,methodology\r\n"
            "Anaïs,2,thousand persons,通常人口,Census 2025\r\n"
            "李雷,2,thousand persons,通常人口,Census 2025\r\n"
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
        goal="People",
        schema=schema(unit=unit),
        dataset_sources=[{"url": base + "/people", "format": fmt, "projection": plan(unit=unit)}],
        identity=["/name"],
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed
    assert [row["population"] for row in result.records] == [2000 if unit else 2] * 2
    manifest_path = output.with_suffix(".json.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cells = [cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population"]
    assets = load_portable_assets(manifest_path)
    assert assets[0].download.dataset.original_bytes == body
    for index, cell in enumerate(cells):
        assert cell["status"] == "resolved"
        descriptors = cell["descriptor_derivations"]
        assert [item["kind"] for item in descriptors] == ["definition", "methodology"]
        assert [item["observed_label"] for item in descriptors] == ["通常人口", "Census 2025"]
        assert all(item["source_value_json"] == '"2"' for item in descriptors)
        assert all(item["row_index"] == index + 1 for item in descriptors)
        assert all(
            item["line_start"] == assets[0].download.dataset.rows[index].line_start
            for item in descriptors
        )
        assert ("unit_derivation" in cell) is unit
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.events(result.run_id, "source_fitness") == []
        summary = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config, export=output)
    assert resumed.records == result.records and seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == summary
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["definition", "methodology"])
@pytest.mark.parametrize("label", ["different", " Census 2025 ", None])
async def test_conflicting_or_missing_declared_descriptors_block_completion(site, kind, label):
    base, bodies, _, config = site
    source = rows()
    source[1][kind] = label
    bodies["/people"] = (200, json.dumps(source).encode())
    result = await arun(
        goal="People",
        schema=schema((kind,)),
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": plan((kind,))}],
        maxrows=2,
        config=config,
    )
    assert not result.completed and result.status == "PAUSED"
    assert result.stop_reason == (
        "dataset_row_gaps" if label is None else "dataset_consistency_gaps"
    )


@pytest.mark.asyncio
async def test_grouped_cells_keep_each_contributor_descriptor_chain(site, tmp_path):
    base, bodies, _, config = site
    bodies["/people"] = (200, json.dumps(rows()).encode())
    output = tmp_path / "group.json"
    result = await arun(
        goal="People",
        schema=schema(),
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": plan()}],
        identity=["/name"],
        groupby="population",
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed and len(result.records) == 1
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    cell = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/population")
    assert cell["status"] == "resolved" and len(cell["contributors"]) == 2
    assert [
        contributor["descriptor_derivations"][0]["row_index"]
        for contributor in cell["contributors"]
    ] == [1, 2]


@pytest.fixture
def context(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    rid = store.create("People", schema(), TaskSpec(), None)
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
        "label",
        "missing",
        "scope",
        "kind",
        "raw_label",
        "candidate",
        "candidate_scope",
        "asset",
        "row",
        "raw",
        "bad_raw",
    ],
)
def test_independent_replay_rejects_auxiliary_evidence_tampering(context, change):
    _, _, page, candidate = context
    assert verify(candidate, page, schema(), TaskSpec()) == []
    assert grounded_projected_descriptors(candidate, page)
    source = next(source for source in page.sources if source.id == "/definition")
    if change == "label":
        source.text = '"Different"'
    if change == "missing":
        page.sources.remove(source)
    if change == "scope":
        source.scope = "foreign"
    if change == "kind":
        source.kind = "link"
    if change == "raw_label":
        page.dataset_source_row_json = page.dataset_source_row_json.replace("通常人口", "Different")
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
    assert not grounded_projected_descriptors(candidate, page)
    assert verify(candidate, page, schema(), TaskSpec())


def test_legacy_plan_serialization_and_invalid_descriptor_declarations():
    legacy = {
        "version": "1",
        "fields": [{"source": "/a", "target": "/b", "conversion": "identity"}],
    }
    assert ProjectionPlan.model_validate(legacy).model_dump() == legacy
    for descriptors in [
        [],
        [{"kind": "unit", "source": "/unit"}],
        [{"kind": "definition"}],
        [{"kind": "definition", "source": "/d", "label": "invented"}],
    ]:
        with pytest.raises(ValidationError):
            ProjectionPlan.model_validate(
                {"fields": [{"source": "/a", "target": "/b", "descriptors": descriptors}]}
            )


@pytest.mark.parametrize("container", [False, True])
def test_duplicate_kinds_and_container_targets_fail_atomically(container):
    declarations = plan(("definition",) if container else ("definition", "definition"))
    source = rows()[0]
    if container:
        source["amount"] = [2]
        declarations["fields"][1]["conversion"] = "identity"
    parsed = capture(json.dumps([source]).encode(), "json").dataset.rows[0]
    with pytest.raises(ProjectionError, match="scalar target and unique kinds"):
        project_row(parsed, ProjectionPlan.model_validate(declarations))


@pytest.mark.asyncio
@pytest.mark.parametrize("unit", [False, True])
async def test_cli_approved_descriptors_enter_new_run_without_changing_original(
    site, tmp_path, unit
):
    base, bodies, seen, config = site
    bodies["/people"] = (200, json.dumps(rows()).encode())
    sources = [{"url": base + "/people", "format": "json"}]
    original = await arun(
        goal="People", schema=schema(), dataset_sources=sources, maxrows=2, config=config
    )
    assert original.status == "PAUSED" and not original.records
    store = ResearchStore(config.sqlite_db_path)
    aid = store.dataset_assets(original.run_id)[0].id
    store.close()
    supplied, report, approved = (
        tmp_path / name for name in ("supplied.json", "review.json", "approved.json")
    )
    supplied.write_text(json.dumps(plan(unit=unit)), encoding="utf-8")
    review = CliRunner().invoke(
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
    assert review.exit_code == 0, review.output
    assert json.loads(report.read_text(encoding="utf-8"))["suggestion"][
        "unmapped_profile_pointers"
    ] == ([] if unit else ["/unit"])
    assert (
        json.loads(approved.read_text(encoding="utf-8"))["fields"][1]["descriptors"]
        == plan()["fields"][1]["descriptors"]
    )
    accepted = await arun(
        goal="People",
        schema=schema(),
        dataset_sources=sources,
        dataset_projection=approved,
        maxrows=2,
        config=config,
    )
    assert accepted.completed and seen == ["/people", "/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert not store.records(original.run_id)
        assert (
            store.events(original.run_id, "dataset_mapping_review")[-1]["payload"]["applied_to_run"]
            is False
        )
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["definition", "methodology"])
async def test_present_but_undeclared_labels_do_not_close_other_requirements(site, kind):
    base, bodies, _, config = site
    bodies["/people"] = (200, json.dumps(rows()).encode())
    result = await arun(
        goal="People",
        schema=schema(),
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": plan((kind,))}],
        maxrows=2,
        config=config,
    )
    assert not result.completed and len(result.records) == 2
    other = "methodology" if kind == "definition" else "definition"
    store = ResearchStore(config.sqlite_db_path)
    try:
        gaps = store.events(result.run_id, "dataset_consistency_gap")[-1]["payload"]["gaps"]
        assert "/population:unknown_" + other in gaps
    finally:
        store.close()


def test_observations_include_declared_descriptors_without_inventing_fitness(context):
    store, rid, page, candidate = context
    store.queue(rid, page.url, 0, None)
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], page, "fixture")
    assert store.accept(rid, page, candidate, [], TaskSpec()) == "accepted"
    runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
    runner.field_semantics = {}
    observed = runner.dataset_comparability_observations()
    assert len(observed) == 1 and observed[0]["pointer"] == "/population"
    assert observed[0]["definition"] == {
        "label": "通常人口",
        "source": "/definition",
        "quote": '"通常人口"',
    }
    assert "unit" not in observed[0] and "authority" not in observed[0]
    assert store.events(rid, "source_fitness") == []
