# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Every advertised adapter enters the public capture, evidence, export and replay workflow."""

import hashlib
from contextlib import closing

import httpx
import pytest
from verboisy import arun
from verboisy.dataset_formats import MIME_TYPES
from verboisy.extractor.download import download_dataset
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.inventory import inspect_dataset_assets
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_extractor.office_fixtures import archive, document, workbook_parts
from tests.test_research.test_local_dataset_workflow import no_external_work

# Reuse the forbidden-provider fixture: these adapters are deterministic.
__all__ = ["no_external_work"]

CASES = [
    ("tsv", b"name\nAlice\n", {"name": {"type": "string"}}, {"name": "Alice"}),
    ("text", "Anaïs\n".encode(), {"text": {"type": "string"}}, {"text": "Anaïs"}),
    ("docx", document(), {"text": {"type": "string"}}, {"text": "Anaïs"}),
    (
        "xlsx",
        archive(workbook_parts()),
        {
            "sheet": {"type": "string"},
            "values": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {"sheet": "People", "values": {"name": "Anaïs"}},
    ),
    (
        "asset",
        b"\x00\xffopaque",
        {"sha256": {"type": "string"}, "byte_count": {"type": "integer"}},
        {"sha256": hashlib.sha256(b"\x00\xffopaque").hexdigest(), "byte_count": 8},
    ),
]


@pytest.mark.parametrize("fmt,raw,properties,expected", CASES, ids=[case[0] for case in CASES])
async def test_local_public_api_portable_replay_and_inventory(
    tmp_path, fmt, raw, properties, expected
):
    source = tmp_path / f"input.{fmt}"
    source.write_bytes(raw)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Explicit source observations",
        schema=schema,
        dataset_sources=[{"format": fmt, "url": source.as_uri()}],
        task={"target_records": 1},
        export=output,
        proof=True,
        config=config,
    )
    assert result.completed and result.records == [{"id": 1, **expected}], result
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        evidence = store.evidence(result.run_id)
        assert len(evidence) == 1
        assert store.load(result.run_id)["reserved"] == 0
        assert store.dataset_assets(result.run_id)[0].download.dataset.original_bytes == raw
    portable = load_portable_assets(tmp_path / "rows.json.manifest.json")
    assert portable[0].download.dataset.original_bytes == raw
    report = inspect_dataset_assets(tmp_path / "run.db", result.run_id)
    assert report["assets"][0]["support_level"] == (
        "capture_and_index" if fmt == "asset" else "deterministic_parse"
    )
    source.unlink()
    config.dataset_local_roots = []
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.completed and resumed.records == result.records
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert store.evidence(result.run_id) == evidence


@pytest.mark.parametrize("fmt,raw,properties,expected", CASES, ids=[case[0] for case in CASES])
async def test_http_adapter_media_types(tmp_path, monkeypatch, fmt, raw, properties, expected):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("verboisy.extractor.download.validate_url", AsyncMock())
    original = httpx.AsyncClient

    def handle(request):
        assert request.headers["accept-encoding"] == "identity"
        mime = "application/pdf" if fmt == "asset" else MIME_TYPES[fmt][0]
        return httpx.Response(200, headers={"content-type": mime}, stream=httpx.ByteStream(raw))

    monkeypatch.setattr(
        "verboisy.extractor.download.httpx.AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(handle),
            **{k: v for k, v in kwargs.items() if k != "transport"},
        ),
    )
    captured = await download_dataset(
        "https://example.test/source",
        Settings(_env_file=None),
        dataset_format=fmt,
        permits=lambda _url: True,
    )
    assert captured.dataset.original_bytes == raw
    assert captured.dataset.rows[0].values == expected


async def test_worksheet_projection_keeps_part_and_cell_derivation(tmp_path):
    source = tmp_path / "table.xlsx"
    source.write_bytes(archive(workbook_parts()))
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Worksheet names",
        schema=["name"],
        dataset_sources=[
            {
                "format": "xlsx",
                "url": source.as_uri(),
                "projection": {"fields": [{"source": "/values/name", "target": "/name"}]},
            }
        ],
        maxrows=1,
        export=output,
        config=config,
    )
    assert result.completed and result.records == [{"id": 1, "name": "Anaïs"}]
    import json

    manifest = json.loads((tmp_path / "rows.json.manifest.json").read_text())
    lineage = next(cell for cell in manifest["cell_lineage"] if cell["pointer"] == "/name")
    assert lineage["source_pointer"] == "/values/name"
    assert lineage["source_value"] == "Anaïs" and lineage["status"] == "resolved"
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        row = store.dataset_assets(result.run_id)[0].download.dataset.rows[0]
        assert row.source_pointer == "/xl/worksheets/sheet1.xml/rows/2"


@pytest.mark.parametrize("fmt,raw,properties,expected", CASES, ids=[case[0] for case in CASES])
def test_cli_accepts_new_format_declarations(tmp_path, monkeypatch, fmt, raw, properties, expected):
    import json

    from typer.testing import CliRunner
    from verboisy.cli.main import app

    source = tmp_path / f"input.{fmt}"
    source.write_bytes(raw)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    monkeypatch.setattr("verboisy.cli.main.Settings", lambda: config)
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Observe the declared file",
            "--schema",
            str(schema_file),
            "--dataset-file",
            f"{fmt}={source}",
            "--maxrows",
            "1",
        ],
    )
    assert result.exit_code == 0 and "Status: COMPLETED" in result.output, result.output
