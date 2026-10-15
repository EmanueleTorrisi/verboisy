# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Actual bounded ingestion/export/resume preserves absent versus nullable cells."""

import csv
import json

from verboisy import arun
from verboisy.utils.config import Settings


async def test_optional_absence_export_and_resume(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('[{"n":1},{"n":2,"name":"B"}]')
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["n"],
            "additionalProperties": False,
        },
    }
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        dataset_local_roots=[str(tmp_path)],
        search_provider="disabled",
    )
    output = tmp_path / "rows.csv"
    result = await arun(
        goal="Synthetic",
        schema=schema,
        task={
            "target_records": 2,
            "dataset_sources": [{"url": source.as_uri(), "format": "json"}],
            "csv_mode": "json",
        },
        config=config,
        export=output,
    )
    assert result.completed and "name" not in result.records[0] and result.records[1]["name"] == "B"
    manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text())
    assert manifest["collection_schema_valid"] is True
    from verboisy.reference_dataset import load_reference_dataset

    assert load_reference_dataset(output).rows == result.records
    assert not any(
        c["output_id"] == 1 and c["pointer"] == "/name" for c in manifest["cell_lineage"]
    )
    with output.open(newline="") as stream:
        cells = list(csv.DictReader(stream))
    assert cells[0]["name"] == "" and cells[1]["name"] == '"B"'
    resumed = await arun(resume=result.run_id, config=config, export=output)
    assert (
        resumed.records == result.records and source.read_text() == '[{"n":1},{"n":2,"name":"B"}]'
    )


async def test_grouped_optional_count_has_explicit_absence_contributor(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('[{"region":"A"},{"region":"A","count":5}]')
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"region": {"type": "string"}, "count": {"type": ["integer", "null"]}},
            "required": ["region"],
        },
    }
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    output = tmp_path / "group.json"
    result = await arun(
        goal="Synthetic",
        schema=schema,
        groupby="region",
        task={"target_records": 2, "dataset_sources": [{"url": source.as_uri(), "format": "json"}]},
        config=config,
        export=output,
    )
    assert result.records == [{"id": 1, "region": "A", "count": 5}]
    manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text())
    cell = next(c for c in manifest["cell_lineage"] if c["pointer"] == "/count")
    assert cell["status"] == "resolved"
    assert cell["contributors"][0]["contribution"] == "absence"


async def test_all_missing_group_count_explains_unknown_inputs(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('[{"region":"B","n":1},{"region":"A","n":2,"count":5}]')
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "region": {"type": "string"},
                "n": {"type": "integer"},
                "count": {"type": "integer"},
            },
            "required": ["region", "n"],
        },
    }
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    output = tmp_path / "group.json"
    result = await arun(
        goal="Synthetic",
        schema=schema,
        groupby="region",
        task={"target_records": 2, "dataset_sources": [{"url": source.as_uri(), "format": "json"}]},
        config=config,
        export=output,
    )
    assert result.records[0]["count"] is None
    cell = next(
        c
        for c in json.loads(output.with_name(output.name + ".manifest.json").read_text())[
            "cell_lineage"
        ]
        if c["output_id"] == 1 and c["pointer"] == "/count"
    )
    assert cell["status"] == "resolved" and cell["steps"][0]["operation"] == "sum"
    assert cell["steps"][0]["reason"] == "no_observed_numeric_inputs"
