# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Current accepted-evidence repair diagnostics are public and portable."""

import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli import main as cli
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore

from tests.test_cli.test_main import completed_result
from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_research import test_dataset_metadata_refresh as metadata
from tests.test_research import test_dataset_year_repair as years
from tests.test_research import test_temporal_projection_ingestion as temporal

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,reason",
    [
        ("unit", "unknown_unit"),
        ("definition", "unknown_definition"),
        ("methodology", "unknown_methodology"),
        ("year", "missing_reference_period"),
    ],
)
async def test_current_report_and_manifest_clear_after_repair(site, tmp_path, kind, reason):
    base, bodies, seen, config = site
    raw = {**temporal.rows()[0], "amount": "2000", "unit": "persons"}
    bodies["/first"] = (200, json.dumps([raw]).encode())
    bodies["/repair"] = (200, json.dumps([raw]).encode())
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Latest population",
        schema=temporal.schema(True, True),
        dataset_sources=[
            {
                "url": base + "/first",
                "format": "json",
                "projection": years.undated_plan()
                if kind == "year"
                else metadata.missing_plan(kind),
            },
            {"url": base + "/repair", "format": "json", "projection": temporal.plan(True, True)},
        ],
        identity=["/name"],
        maxrows=1,
        max_steps=1,
        export=output,
        config=config,
    )
    assert not result.completed and result.stop_reason == "dataset_source_budget"
    report = result.dataset_consistency
    assert report["scope"] == "accepted_records"
    assert report["gaps"] == ["/population:" + reason]
    assert len(report["repairs"]) == 1
    if report["repairs"]:
        repair = report["repairs"][0]
        assert repair["reason"] == reason and repair["pointer"] == "/population"
    store = ResearchStore(config.sqlite_db_path)
    try:
        if report["repairs"]:
            assert (
                report["repairs"][0]["record_id"] == store.evidence(result.run_id)[0]["record_id"]
            )
        # Reporting a budget pause does not manufacture a persisted gap event.
        assert store.events(result.run_id, "dataset_consistency_gap") == []
        export_dataset(
            store,
            result.run_id,
            tmp_path / "extension.json",
            temporal.schema(True, True),
            TaskSpec(),
            metadata={"dataset_consistency": {"gaps": [], "repairs": []}},
            dataset_consistency=report,
        )
        extension = json.loads((tmp_path / "extension.json.manifest.json").read_text())
        assert extension["dataset_consistency"] == report
    finally:
        store.close()
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    assert manifest["dataset_consistency"] == report
    assert not manifest["truth_verified"] and not manifest["global_completeness_claimed"]
    bodies.pop("/first")
    resumed = await arun(resume=result.run_id, config=config, export=output)
    assert resumed.completed and len(resumed.records) == 1
    assert resumed.dataset_consistency == {"scope": "accepted_records", "gaps": [], "repairs": []}
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    assert manifest["dataset_consistency"] == resumed.dataset_consistency
    store = ResearchStore(config.sqlite_db_path)
    try:
        events = store.events(result.run_id)
    finally:
        store.close()
    bodies.clear()
    completed = await arun(resume=result.run_id, config=config)
    assert completed.dataset_consistency == resumed.dataset_consistency
    assert seen == ["/first", "/repair"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.events(result.run_id) == events
    finally:
        store.close()


@pytest.mark.parametrize("gaps", [[], ["/population:unknown_unit"]])
def test_cli_reports_current_gaps_and_stable_repair_records(monkeypatch, tmp_path, gaps):
    repair = {"record_id": "stable-a", "pointer": "/population", "reason": "unknown_unit"}
    result = replace(
        completed_result(tmp_path),
        completed=not gaps,
        status="PAUSED" if gaps else "COMPLETED",
        stop_reason="dataset_consistency_gaps" if gaps else "target_met",
        dataset_consistency={
            "scope": "accepted_records",
            "gaps": gaps,
            "repairs": [repair] if gaps else [],
        },
    )
    monkeypatch.setattr(cli, "run", lambda **_kwargs: result)
    response = CliRunner().invoke(cli.app, ["run", "--resume", "run-1"])
    assert response.exit_code == (2 if gaps else 0)
    if gaps:
        assert "Dataset gap: /population:unknown_unit" in response.output
        assert "Repair record stable-a at /population: unknown_unit" in response.output
    else:
        assert "Dataset gap:" not in response.output and "Repair record" not in response.output


def test_direct_export_has_no_implied_evaluation(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    schema = fixtures.schema({"name": {"type": "string"}})
    task = TaskSpec()
    rid = store.create("Rows", schema, task, None)
    try:
        manifest = export_dataset(
            store,
            rid,
            tmp_path / "rows.json",
            schema,
            task,
            metadata={"dataset_consistency": {"gaps": [], "repairs": []}},
        )
        assert json.loads(manifest.read_text())["dataset_consistency"] is None
    finally:
        store.close()
