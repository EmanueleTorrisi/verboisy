# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared dataset CLI and API boundary regressions."""

import importlib
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy import arun
from verboisy.cli.main import app
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_research import test_dataset_ingestion as fixtures

site = fixtures.site
no_paid_or_browser_work = fixtures.no_paid_or_browser_work


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b"name\r\nA\r\nB\r\n"),
        ("json", b'[{"name":"A"},{"name":"B"}]'),
        ("jsonl", b'{"name":"A"}\n{"name":"B"}\n'),
    ],
)
def test_cli_ingestion_resume(site, tmp_path, fmt, body):
    base, bodies, seen, config = site
    bodies["/people?v=1"] = (200, body)
    cli = importlib.import_module("verboisy.cli.main")
    output = tmp_path / "rows.json"
    with patch.object(cli, "Settings", return_value=config):
        args = [
            "run",
            "--goal",
            "Names",
            "--schema",
            "[name]",
            "--dataset-source",
            f"{fmt}={base}/people?v=1",
            "--maxrows",
            "2",
            "--export",
            str(output),
            "--proof",
        ]
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(output.read_text()) == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        store = ResearchStore(config.sqlite_db_path)
        try:
            rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
            task = json.loads(store.load(rid)["task_json"])
            assert task["csv_mode"] == "spreadsheet"
            assert task["dataset_sources"] == [
                {"url": base + "/people?v=1", "format": fmt, "projection": None}
            ]
        finally:
            store.close()
        bodies.clear()
        resumed = CliRunner().invoke(app, ["run", "--resume", rid])
        assert resumed.exit_code == 0, resumed.output
        conflict = CliRunner().invoke(
            app, ["run", "--resume", rid, "--dataset-source", f"{fmt}={base}/people?v=1"]
        )
        assert conflict.exit_code == 1
        assert "Resume uses its saved" in conflict.output
    assert seen == ["/people?v=1"]
    assert output.with_suffix(".json.assets.json").exists()
    assert output.with_suffix(".proof.txt").exists()


@pytest.mark.parametrize(
    "declaration", ["json", "xml=https://example.test", "json=", "=https://example.test"]
)
def test_cli_invalid(declaration, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["run", "--goal", "Names", "--schema", "[name]", "--dataset-source", declaration]
    )
    assert result.exit_code == 1
    assert "--dataset-source requires" in result.output


def test_help():
    assert "--dataset-source" in CliRunner().invoke(app, ["--help"]).output
    assert "json=URL" in CliRunner().invoke(app, ["run", "--help"]).output
    assert CliRunner().invoke(app, ["run", "--dataset-source"]).exit_code == 2


@pytest.mark.asyncio
async def test_api_declarations(site):
    base, bodies, seen, config = site
    sources = [{"url": base + "/names", "format": "json"}]
    bodies["/names"] = (200, b'[{"name":"A"}]')
    result = await arun(
        goal="Names",
        schema="[name]",
        dataset_sources=sources,
        task={"dataset_sources": sources, "target_records": 1},
        config=config,
    )
    assert result.completed
    with pytest.raises(VerboisyError, match="Invalid dataset source"):
        await arun(
            goal="Names", schema="[name]", dataset_sources=[{"format": "xml"}], config=config
        )
    with pytest.raises(VerboisyError, match="conflict with task"):
        await arun(
            goal="Names",
            schema="[name]",
            dataset_sources=[],
            task={"dataset_sources": sources},
            config=config,
        )
    with pytest.raises(VerboisyError, match="mixed with browser"):
        await arun(
            goal="Names",
            schema="[name]",
            dataset_sources=sources,
            task={"seed_urls": [base]},
            config=config,
        )
    assert seen == ["/names"]


def test_repeated_sources_budget_resume(site, tmp_path):
    base, bodies, seen, config = site
    bodies["/first"] = (200, b'[{"name":"A"}]')
    bodies["/second"] = (200, b'[{"name":"B"}]')
    cli = importlib.import_module("verboisy.cli.main")
    output = tmp_path / "rows.json"
    with patch.object(cli, "Settings", return_value=config):
        result = CliRunner().invoke(
            app,
            [
                "run",
                "--goal",
                "Names",
                "--schema",
                "[name]",
                "--maxrows",
                "2",
                "--dataset-source",
                f"json={base}/first",
                "--dataset-source",
                f"json={base}/second",
                "--max-steps",
                "1",
                "--export",
                str(output),
            ],
        )
        assert result.exit_code != 0
        store = ResearchStore(config.sqlite_db_path)
        try:
            rid = store.db.execute("SELECT id FROM research_runs").fetchone()[0]
            assert store.load(rid)["reason"] == "dataset_source_budget"
        finally:
            store.close()
        resumed = CliRunner().invoke(app, ["run", "--resume", rid, "--max-steps", "1"])
        assert resumed.exit_code == 0, resumed.output
    assert seen == ["/first", "/second"]
    assert json.loads(output.read_text()) == [
        {"id": 1, "name": "A"},
        {"id": 2, "name": "B"},
    ]
