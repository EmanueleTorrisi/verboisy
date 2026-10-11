# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reviewed suggestions use the existing source-bound projection ingestion path."""

import json

import pytest
from verboisy import arun
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.mapping import SchemaMappingError, suggest_mapping, validate_mapping
from verboisy.extractor.profile import profile_dataset
from verboisy.storage.research import ResearchStore

from tests.test_research import test_dataset_ingestion as fixtures

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.asyncio
async def test_reviewed_alias_plan_ingestion_exports_and_resume(site, tmp_path):
    base, bodies, seen, config = site
    body = (
        '[{"Name":"Anaïs","age":31,"extra":"drop"},' '{"Name":"李雷","age":22,"extra":"drop"}]'
    ).encode()
    bodies["/rows"] = (200, body)
    data = parse_dataset(body, "json")
    target = fixtures.schema({"name": {"type": "string"}, "age": {"type": "integer"}})
    suggestion = suggest_mapping(profile_dataset(data), target, aliases={"/name": ["/Name"]})
    assert suggestion.unmapped_profile_pointers == ("/extra",)
    plan = validate_mapping(data, target, suggestion)
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Names",
        schema=target,
        dataset_sources=[
            {"url": base + "/rows", "format": "json", "projection": plan.model_dump()},
        ],
        identity=["/name"],
        maxrows=2,
        export=output,
        config=config,
    )
    assert result.completed
    assert result.records == [
        {"id": 1, "name": "Anaïs", "age": 31},
        {"id": 2, "name": "李雷", "age": 22},
    ]
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    name = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/name")
    assert name["source_pointer"] == "/Name"
    assert name["source_value"] == "Anaïs"
    assert name["status"] == "resolved"
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert (
            store.dataset_assets(result.run_id)[0].download.dataset.sha256
            == suggestion.asset_sha256
        )
        assert (
            store.evidence(result.run_id)[0]["snapshot"]["dataset_projection"] == plan.model_dump()
        )
    finally:
        store.close()
    bodies.clear()
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.records == result.records
    assert seen == ["/rows"]


def test_unobserved_type_change_blocks_plan_before_ingestion(site):
    _, _, seen, _ = site
    data = parse_dataset(b'[{"name":"A","age":31},{"name":"B","age":"unknown"}]', "json")
    target = fixtures.schema({"name": {"type": "string"}, "age": {"type": "integer"}})
    suggestion = suggest_mapping(profile_dataset(data, sample_rows=1), target)
    assert suggestion.plan is not None
    with pytest.raises(SchemaMappingError, match="full-row"):
        validate_mapping(data, target, suggestion)
    assert seen == []
