# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Projection ingestion replays captured rows and rejects altered evidence."""

import json
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.evidence.models import FieldRule, ProjectionPlan, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.extractor.ingestion import row_evidence
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures
from tests.test_storage.test_dataset_assets import capture

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work
PLAN = {
    "fields": [
        {"source": "/Person", "target": "/name"},
        {"source": "/Age", "target": "/years", "conversion": "integer"},
    ]
}
SCHEMA = fixtures.schema({"name": {"type": "string"}, "years": {"type": "integer"}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", "Person,Age,unused\r\nAnaïs,31,ignore\r\n李雷,22,ignore\r\n".encode()),
        (
            "json",
            '[{"Person":"Anaïs","Age":"31","unused":0},{"Person":"李雷","Age":"22"}]'.encode(),
        ),
        ("jsonl", '{"Person":"Anaïs","Age":"31"}\n{"Person":"李雷","Age":"22"}\n'.encode()),
    ],
)
async def test_projection_exports_and_offline_resume(site, tmp_path, fmt, body):
    base, bodies, seen, config = site
    bodies["/people"] = (200, body)
    output = tmp_path / "people.json"
    result = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=[
            {"url": base + "/people", "format": fmt, "projection": PLAN},
        ],
        maxrows=2,
        identity=["/name"],
        export=output,
        proof=True,
        config=config,
    )
    assert result.completed
    assert result.records == [
        {"id": 1, "name": "Anaïs", "years": 31},
        {"id": 2, "name": "李雷", "years": 22},
    ]
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    cell = next(c for c in manifest["cell_lineage"] if c["pointer"] == "/years")
    assert cell["source_value"] == "31"
    assert cell["source_pointer"] == "/Age"
    assert cell["steps"][0]["operation"] == "dataset_projection"
    assert cell["status"] == "resolved"
    assets = load_portable_assets(output.with_suffix(".json.manifest.json"))
    assert assets[0].download.dataset.original_bytes == body
    store = ResearchStore(config.sqlite_db_path)
    try:
        context = store.evidence(result.run_id)[0]
        assert context["snapshot"]["dataset_source_row_json"]
        assert context["candidate"]["evidence"]["/years"]["quote"] == '"31"'
        before = store.summary(result.run_id)
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, export=output, config=config)
    assert resumed.records == result.records
    assert seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert store.summary(result.run_id) == before
    finally:
        store.close()


@pytest.mark.asyncio
async def test_rejected_projection_resume_and_schema(site):
    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Person":"A","Age":"bad"},{"Person":"B","Age":"22"}]')
    sources = [{"url": base + "/people", "format": "json", "projection": PLAN}]
    first = await arun(
        goal="Names", schema=SCHEMA, dataset_sources=sources, maxrows=2, config=config
    )
    assert first.status == "PAUSED"
    assert first.stop_reason == "dataset_row_gaps"
    assert first.records == [{"id": 1, "name": "B", "years": 22}]
    second = await arun(resume=first.run_id, config=config)
    assert second.records == first.records
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(first.run_id, "dataset_projection_failure")) == 1
    finally:
        store.close()
    bad_schema = fixtures.schema({"name": {"type": "string"}, "years": {"type": "string"}})
    third = await arun(
        goal="Names", schema=bad_schema, dataset_sources=sources, maxrows=2, config=config
    )
    assert third.records == []
    assert third.stop_reason == "dataset_row_gaps"
    assert seen == ["/people", "/people"]


@pytest.mark.asyncio
async def test_interrupted_accept_restores_projected_journal(site):
    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Person":"A","Age":"31"}]')
    original = ResearchStore.event

    def interrupt(self, rid, kind, payload):
        if kind == "dataset_row":
            raise KeyboardInterrupt()
        return original(self, rid, kind, payload)

    # Simulate an event-write interruption after the accepted record commit.
    with patch.object(ResearchStore, "event", interrupt), pytest.raises(KeyboardInterrupt):
        await arun(
            goal="Names",
            schema=SCHEMA,
            dataset_sources=[
                {"url": base + "/people", "format": "json", "projection": PLAN},
            ],
            maxrows=1,
            config=config,
        )
    store = ResearchStore(config.sqlite_db_path)
    try:
        rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
    finally:
        store.close()
    result = await arun(resume=rid, config=config)
    assert result.completed
    assert seen == ["/people"]
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert len(store.events(rid, "dataset_row")) == 1
    finally:
        store.close()


def grounded():
    # Use a verified persisted asset as the projection evidence origin.
    from verboisy.storage.assets import StoredDatasetAsset

    download = capture(b'[{"name":"A","population":"31"}]', "json")
    asset = StoredDatasetAsset("fixture", "run", "2026-01-01", download)
    projection = ProjectionPlan.model_validate(
        {
            "fields": [
                {"source": "/name", "target": "/name"},
                {"source": "/population", "target": "/years", "conversion": "integer"},
            ]
        }
    )
    page, candidate = row_evidence(asset, download.dataset.rows[0], projection)
    return page, candidate


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("value", "dataset_projection_mismatch"),
        ("raw_missing", "dataset_projection_not_grounded"),
        ("asset_missing", "dataset_projection_not_grounded"),
        ("row_missing", "dataset_projection_not_grounded"),
        ("raw_invalid", "dataset_projection_not_grounded"),
        ("raw_changed", "dataset_projection_mismatch"),
        ("quote", "/years:unsupported_dataset_projection"),
        ("source_text", "/years:unsupported_dataset_projection"),
        ("plan_missing", "/years:dataset_projection_not_grounded"),
        ("transform", "/years:dataset_projection_expected"),
    ],
)
def test_altered_projection_evidence(mutation, expected):
    page, candidate = grounded()
    assert verify(candidate, page, SCHEMA, TaskSpec()) == []
    if mutation == "value":
        candidate.record["years"] = 32
    elif mutation == "raw_missing":
        page.dataset_source_row_json = None
    elif mutation == "asset_missing":
        page.dataset_asset_id = None
    elif mutation == "row_missing":
        page.dataset_row_index = None
    elif mutation == "raw_invalid":
        page.dataset_source_row_json = "bad"
    elif mutation == "raw_changed":
        page.dataset_source_row_json = '{"name":"A","population":"32"}'
    elif mutation == "quote":
        candidate.evidence["/years"].quote = "31"
    elif mutation == "source_text":
        page.sources[-1].text = "31"
    elif mutation == "transform":
        candidate.evidence["/years"].transform = "integer"
    else:
        page.dataset_projection = None
    assert expected in verify(candidate, page, SCHEMA, TaskSpec())


@pytest.mark.parametrize("rule", [FieldRule(mapping={"31": "31"}), FieldRule(external=True)])
def test_projection_does_not_bypass_field_rules(rule):
    page, candidate = grounded()
    assert "/years:dataset_rule_not_supported" in verify(
        candidate,
        page,
        SCHEMA,
        TaskSpec(field_rules={"/years": rule}),
    )


@pytest.mark.asyncio
async def test_common_plan_validation_and_conflicts(site, tmp_path):
    from verboisy.utils.exceptions import VerboisyError

    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Person":"A","Age":"31"}]')
    sources = [{"url": base + "/people", "format": "json"}]
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(PLAN), encoding="utf-8")
    result = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=sources,
        dataset_projection=plan_file,
        maxrows=1,
        config=config,
    )
    assert result.completed
    same = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=[dict(sources[0], projection=PLAN)],
        dataset_projection=ProjectionPlan.model_validate(PLAN),
        maxrows=1,
        config=config,
    )
    assert same.completed
    for kwargs, message in [
        (
            {"dataset_projection": {"fields": []}, "dataset_sources": sources},
            "Invalid dataset projection",
        ),
        ({"dataset_projection": PLAN}, "requires declared"),
        (
            {
                "dataset_projection": {"fields": [{"source": "/Person", "target": "/name"}]},
                "dataset_sources": [dict(sources[0], projection=PLAN)],
            },
            "conflicts",
        ),
        ({"dataset_projection": PLAN, "resume": result.run_id}, "Resume uses its saved"),
    ]:
        with pytest.raises(VerboisyError, match=message):
            await arun(
                config=config,
                **({"goal": "Names", "schema": SCHEMA} if not kwargs.get("resume") else {}),
                **kwargs,
            )
    with pytest.raises(VerboisyError, match="differ from schema/task inputs"):
        await arun(
            goal="Names",
            schema=SCHEMA,
            dataset_sources=sources,
            dataset_projection=plan_file,
            export=plan_file,
            config=config,
        )
    assert len(seen) == 2


def test_cli_projection_plan(site, tmp_path):
    import importlib

    from typer.testing import CliRunner
    from verboisy.cli.main import app

    base, bodies, seen, config = site
    bodies["/people"] = (200, b"Person,Age\r\nAna,31\r\n")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(PLAN), encoding="utf-8")
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA), encoding="utf-8")
    cli = importlib.import_module("verboisy.cli.main")
    with patch.object(cli, "Settings", return_value=config):
        result = CliRunner().invoke(
            app,
            [
                "run",
                "--goal",
                "Names",
                "--schema",
                str(schema_file),
                "--dataset-source",
                f"csv={base}/people",
                "--dataset-projection",
                str(plan_file),
                "--maxrows",
                "1",
                "--export",
                str(tmp_path / "cli.json"),
            ],
        )
        assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "cli.json").read_text(encoding="utf-8")) == [
        {"id": 1, "name": "Ana", "years": 31}
    ]
    assert seen == ["/people"]


@pytest.mark.asyncio
async def test_resume_rejects_changed_saved_plan(site):
    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Person":"A","Age":"31"}]')
    result = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=[{"url": base + "/people", "format": "json", "projection": PLAN}],
        maxrows=1,
        config=config,
    )
    store = ResearchStore(config.sqlite_db_path)
    try:
        saved = json.loads(store.load(result.run_id)["task_json"])
        saved["dataset_sources"][0]["projection"] = None
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (json.dumps(saved), result.run_id)
        )
        store.db.execute(
            "DELETE FROM events WHERE run_id=? AND kind='dataset_row'", (result.run_id,)
        )
        store.db.commit()
    finally:
        store.close()
    from verboisy.storage.assets import DatasetAssetError

    with pytest.raises(DatasetAssetError, match="saved declarations"):
        await arun(resume=result.run_id, config=config)
    assert seen == ["/people"]


def test_nested_identity_projection():
    from verboisy.storage.assets import StoredDatasetAsset

    download = capture(b'[{"raw":{"children":["A",null]},"flag":true}]', "json")
    asset = StoredDatasetAsset("fixture", "run", "2026-01-01", download)
    plan = ProjectionPlan.model_validate(
        {
            "fields": [
                {"source": "/raw", "target": "/nested"},
                {"source": "/flag", "target": "/enabled", "conversion": "boolean"},
            ]
        }
    )
    page, candidate = row_evidence(asset, download.dataset.rows[0], plan)
    schema = fixtures.schema(
        {
            "nested": {
                "type": "object",
                "properties": {
                    "children": {"type": "array", "items": {"type": ["string", "null"]}},
                },
                "required": ["children"],
                "additionalProperties": False,
            },
            "enabled": {"type": "boolean"},
        }
    )
    assert verify(candidate, page, schema, TaskSpec()) == []
    assert candidate.evidence["/nested/children/0"].source == "/raw/children/0"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_asset", "changed_candidate", "changed_snapshot"])
async def test_completed_projection_rejects_corrupt_binding(site, mutation):
    from verboisy.storage.assets import DatasetAssetError

    base, bodies, seen, config = site
    bodies["/people"] = (200, b'[{"Person":"A","Age":"31"}]')
    result = await arun(
        goal="Names",
        schema=SCHEMA,
        dataset_sources=[
            {"url": base + "/people", "format": "json", "projection": PLAN},
        ],
        maxrows=1,
        config=config,
    )
    store = ResearchStore(config.sqlite_db_path)
    try:
        if mutation == "changed_candidate":
            row = store.db.execute(
                "SELECT id,payload FROM candidates WHERE run_id=?", (result.run_id,)
            ).fetchone()
            payload = json.loads(row[1])
            payload["record"]["years"] = 32
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE id=?", (json.dumps(payload), row[0])
            )
        else:
            row = store.db.execute(
                "SELECT id,payload FROM snapshots WHERE run_id=?", (result.run_id,)
            ).fetchone()
            payload = json.loads(row[1])
            if mutation == "missing_asset":
                payload["dataset_asset_id"] = None
            else:
                payload["dataset_source_row_json"] = '{"Person":"A","Age":"32"}'
            store.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?", (json.dumps(payload), row[0])
            )
        store.db.commit()
    finally:
        store.close()
    with pytest.raises(DatasetAssetError, match="captured source"):
        await arun(resume=result.run_id, config=config)
    assert seen == ["/people"]
