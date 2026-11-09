# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check and use versioned recipes without changing ordinary run behavior."""

import hashlib
import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import verboisy
from typer.testing import CliRunner
from verboisy.utils.config import Settings

cli = import_module("verboisy.cli.main")


@pytest.fixture
def recipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "research.db"),
        dataset_local_roots=[str(tmp_path)],
        model_request_budget=1,
        search_request_budget=0,
        search_provider="disabled",
        browser_auto_install=False,
    )
    monkeypatch.setattr(cli, "Settings", lambda **_kwargs: config)
    fail = AsyncMock(side_effect=AssertionError("Unexpected external operation"))
    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", fail)
    monkeypatch.setattr("verboisy.api.web_search", fail)
    monkeypatch.setattr("verboisy.browser.context.BrowserManager.start", fail)
    value = {
        "version": "1",
        "name": "local-catalog",
        "revision": 1,
        "goal": "Prepare the supplied catalog.",
        "schema": ["name"],
        "task": {
            "target_records": 1,
            "dataset_sources": [{"url": "input:catalog", "format": "jsonl"}],
        },
    }
    path = tmp_path / "workflow.json"
    path.write_bytes(json.dumps(value).encode())
    return path, value


@pytest.mark.parametrize(
    "schema",
    [
        ["name"],
        {"type": "object", "properties": {"name": {"type": "string"}}},
        {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    ],
)
def test_workflow_check_validates_without_binding_or_running(recipe, tmp_path, schema):
    path, value = recipe
    value["schema"] = schema
    path.write_bytes(json.dumps(value).encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    outcome = CliRunner().invoke(cli.app, ["workflow-check", str(path), "--sha256", digest])
    assert outcome.exit_code == 0, outcome.output
    result = json.loads(outcome.stdout)
    assert result["workflow_origin"]["sha256"] == digest
    assert result["required_inputs"] == ["catalog"] and result["validated"]
    assert not (tmp_path / "research.db").exists()


def test_workflow_check_refuses_invalid_task_schema_and_hash(recipe, tmp_path):
    path, value = recipe
    runner = CliRunner()
    args = ["workflow-check", str(path)]
    pin = runner.invoke(cli.app, [*args, "--sha256", "0" * 64])
    assert pin.exit_code == 1 and "differs" in pin.stderr
    for key, replacement, reason in (
        ("task", {"unknown": True}, "Invalid workflow task"),
        ("schema", {"type": "string"}, "Top-level schema"),
    ):
        path.write_bytes(json.dumps({**value, key: replacement}).encode())
        refused = runner.invoke(cli.app, args)
        assert refused.exit_code == 1 and not refused.stdout
        assert reason in refused.stderr
    assert not (tmp_path / "research.db").exists()


def test_run_cli_binds_a_recipe_and_exports_its_origin(recipe, tmp_path):
    path, _ = recipe
    data = tmp_path / "data = current.jsonl"
    data.write_bytes(b'{"name":"workflow value"}\n')
    output = tmp_path / "output.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            "--workflow",
            str(path),
            "--workflow-input",
            f"catalog={data}",
            "--workflow-sha256",
            digest,
            "--export",
            str(output),
            "--proof",
            "--no-animation",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_bytes())[0]["name"] == "workflow value"
    info = json.loads(output.with_suffix(".json.manifest.json").read_bytes())
    assert info["workflow_origin"]["sha256"] == digest
    assert info["model_request_units"] == 0


def test_bad_cli_binding_reports_error_before_creating_a_run(recipe, tmp_path):
    path, _ = recipe
    result = CliRunner().invoke(
        cli.app,
        ["run", "--workflow", str(path), "--workflow-input", "catalog", "--no-animation"],
    )
    assert result.exit_code == 1 and "NAME=PATH" in result.output
    assert not (tmp_path / "research.db").exists()


def test_workflow_help_does_not_load_the_run_engine():
    root = Path(verboisy.__file__).resolve().parents[1]
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from typer.testing import CliRunner
from verboisy.cli.main import app
for args in (["run", "--help"], ["workflow-check", "--help"]):
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
assert "verboisy.api" not in sys.modules
assert "verboisy.extractor.schema_builder" not in sys.modules
assert "litellm" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code, str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
