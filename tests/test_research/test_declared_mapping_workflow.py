# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A CLI-approved conversion plan enters the existing source-bound ingestion workflow."""

import json

import pytest
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli.main import app
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.asyncio
async def test_cli_review_and_new_run_with_approved_date_plan(site, tmp_path):
    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Name":"Ana","DOB":"03/04/2025","Age":"22"}]')
    schema = fixtures.schema(
        {
            "name": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "years": {"type": "integer"},
        }
    )
    sources = [{"url": base + "/people", "format": "json"}]
    original = await arun(
        goal="People", schema=schema, dataset_sources=sources, maxrows=1, config=config
    )
    assert original.status == "PAUSED" and original.records == []
    store = ResearchStore(config.sqlite_db_path)
    aid = store.dataset_assets(original.run_id)[0].id
    store.close()
    supplied = tmp_path / "supplied.json"
    declarations = {
        "fields": [
            {"source": "/Name", "target": "/name"},
            {"source": "/DOB", "target": "/date", "conversion": "date_dmy"},
            {"source": "/Age", "target": "/years", "conversion": "integer"},
        ]
    }
    supplied.write_text(json.dumps(declarations))
    report = tmp_path / "review.json"
    approved = tmp_path / "approved.json"
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
    assert seen == ["/people"]
    assert json.loads(report.read_text())["proposal_kind"] == "declared_plan"
    store = ResearchStore(config.sqlite_db_path)
    try:
        event = store.events(original.run_id, "dataset_mapping_review")[-1]["payload"]
        assert event["decision"] == "approved" and event["applied_to_run"] is False
        assert event["plan"] == json.loads(approved.read_text())
        assert store.records(original.run_id) == []
    finally:
        store.close()
    output = tmp_path / "people.json"
    accepted = await arun(
        goal="People",
        schema=schema,
        dataset_sources=sources,
        dataset_projection=approved,
        maxrows=1,
        export=output,
        config=config,
    )
    assert accepted.completed
    assert accepted.records == [{"id": 1, "name": "Ana", "date": "03/04/2025", "years": 22}]
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    date = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/date")
    assert date["source_value"] == "03/04/2025" and date["status"] == "resolved"
    assert date["raw_value"] == "2025-04-03"
    assert date["steps"][-1]["operation"] == "presentation"
    bodies.clear()
    resumed = await arun(resume=accepted.run_id, config=config)
    assert resumed.records == accepted.records
    assert seen == ["/people", "/people"]
