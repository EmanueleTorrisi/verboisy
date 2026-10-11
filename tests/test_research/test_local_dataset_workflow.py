# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Local CLI/API ingestion keeps the same evidence, export and immutable resume contract."""

import json
from contextlib import closing
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli.main import app
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings


@pytest.fixture(autouse=True)
def no_external_work():
    with (
        patch(
            "verboisy.browser.context.BrowserManager.start",
            new=AsyncMock(side_effect=AssertionError("browser")),
        ),
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            new=AsyncMock(side_effect=AssertionError("model")),
        ),
        patch("verboisy.api.web_search", new=AsyncMock(side_effect=AssertionError("search"))),
        patch(
            "verboisy.extractor.ingestion.download_dataset",
            new=AsyncMock(side_effect=AssertionError("HTTP")),
        ),
    ):
        yield


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b"name\nAlice\nBob\n"),
        ("json", b'[{"name":"Alice"},{"name":"Bob"}]'),
        ("jsonl", b'{"name":"Alice"}\n{"name":"Bob"}\n'),
    ],
)
async def test_local_api_capture_export_and_resume_after_source_removal(tmp_path, fmt, body):
    source = tmp_path / f"source.{fmt}"
    source.write_bytes(body)
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        dataset_local_roots=[str(tmp_path)],
        search_provider="disabled",
    )
    output = tmp_path / "rows.json"
    result = await arun(
        goal="Names",
        schema=["name"],
        dataset_sources=[{"format": fmt, "url": source.as_uri()}],
        task={"target_records": 2, "identity_fields": ["/name"]},
        export=output,
        proof=True,
        config=config,
    )
    assert result.status == "COMPLETED" and len(result.records) == 2
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        original = store.evidence(result.run_id)
        assert len(original) == 2
        assert store.dataset_assets(result.run_id)[0].download.dataset.original_bytes == body
        assert store.load(result.run_id)["reserved"] == 0
    source.unlink()
    config.dataset_local_roots = []
    resumed = await arun(resume=result.run_id, config=config)
    assert resumed.status == "COMPLETED" and resumed.records == result.records
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert store.evidence(result.run_id) == original
    portable = load_portable_assets(tmp_path / "rows.json.manifest.json")
    assert portable[0].download.dataset.original_bytes == body


async def test_ungranted_source_fails_without_asset_or_model_work(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('[{"name":"Alice"}]')
    config = Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db"))
    result = await arun(
        goal="Names",
        schema=["name"],
        dataset_sources=[{"format": "json", "url": source.as_uri()}],
        config=config,
    )
    assert result.status == "FAILED" and result.records == []
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert store.dataset_assets(result.run_id) == []
        assert store.events(result.run_id, "dataset_source_failure")


def test_cli_declares_local_path_and_keeps_resume_independent_of_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "names with spaces.json"
    source.write_text('[{"name":"Alice"}]')
    monkeypatch.setenv("DATASET_LOCAL_ROOTS", json.dumps([str(tmp_path)]))
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "run.db"))
    monkeypatch.setattr(
        "verboisy.cli.main.Settings",
        lambda: Settings(
            _env_file=None,
            sqlite_db_path=str(tmp_path / "run.db"),
            dataset_local_roots=[str(tmp_path)],
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Names",
            "--schema",
            "[name]",
            "--dataset-file",
            "json=names with spaces.json",
            "--maxrows",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Status: COMPLETED" in result.output, result.output
    with closing(ResearchStore(tmp_path / "run.db", read_only=True)) as store:
        rid = store.db.execute(
            "SELECT id FROM research_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        state = store.load(rid)
        rid = state["id"]
        assert json.loads(state["task_json"])["dataset_sources"][0]["url"] == source.as_uri()
    source.unlink()
    resumed = CliRunner().invoke(app, ["run", "--resume", rid])
    assert resumed.exit_code == 0, resumed.output
    conflict = CliRunner().invoke(
        app, ["run", "--resume", rid, "--dataset-file", "json=source.json"]
    )
    assert conflict.exit_code == 1


@pytest.mark.parametrize("declaration", ["json", "xml=file", "csv=", "=file"])
def test_invalid_cli_local_declarations(tmp_path, monkeypatch, declaration):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["run", "--goal", "Names", "--schema", "[name]", "--dataset-file", declaration]
    )
    assert result.exit_code == 1
    assert "--dataset-file requires" in result.output


def test_cli_can_combine_explicit_uri_and_file_declarations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('[{"name":"Alice"}]')
    second.write_text('[{"name":"Bob"}]')
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), dataset_local_roots=[str(tmp_path)]
    )
    monkeypatch.setattr("verboisy.cli.main.Settings", lambda: config)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Names",
            "--schema",
            "[name]",
            "--dataset-source",
            f"json={first.as_uri()}",
            "--dataset-file",
            "json=second.json",
            "--maxrows",
            "2",
        ],
    )
    assert result.exit_code == 0 and "Status: COMPLETED" in result.output, result.output
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        rid = store.db.execute("SELECT id FROM research_runs LIMIT 1").fetchone()[0]
        assert len(store.records(rid)) == 2
