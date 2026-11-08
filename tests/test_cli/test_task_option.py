# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The documented CLI task file reaches the real API without losing path protections."""

import json
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.main import get_command
from typer.testing import CliRunner
from verboisy.utils.config import Settings

cli = import_module("verboisy.cli.main")


@pytest.fixture(autouse=True)
def no_external_services():
    with (
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            new=AsyncMock(side_effect=AssertionError("model")),
        ),
        patch("verboisy.api.web_search", new=AsyncMock(side_effect=AssertionError("search"))),
        patch(
            "verboisy.browser.context.BrowserManager.start",
            new=AsyncMock(side_effect=AssertionError("browser")),
        ),
    ):
        yield


@pytest.fixture
def local_cli(monkeypatch, tmp_path):
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
    monkeypatch.setattr(cli, "Settings", lambda: config)
    return CliRunner()


def test_acceptance_runner_options_are_real_cli_parameters():
    command = get_command(cli.app).commands["run"]
    names = {name for param in command.params for name in param.opts}
    assert {
        "--goal",
        "--schema",
        "--task",
        "--dataset-file",
        "--export",
        "--proof",
        "--mass-unit",
        "--length-unit",
        "--date-format",
        "--maxrows",
        "--resume",
    } <= names


def test_task_option_is_in_help(local_cli):
    result = local_cli.invoke(cli.app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--task" in result.output


def test_task_path_is_forwarded_without_losing_input_identity(local_cli, tmp_path):
    task = tmp_path / "advanced task.json"
    task.write_text('{"csv_mode":"json"}', encoding="utf-8")
    # Stop at the API boundary; the separate integration case exercises execution.
    with patch.object(cli, "run", side_effect=KeyboardInterrupt) as call:
        result = local_cli.invoke(
            cli.app, ["run", "--goal", "Prepare data", "--schema", "[name]", "--task", str(task)]
        )
    assert result.exit_code == 130
    assert call.call_args.kwargs["task"] == task
    assert isinstance(call.call_args.kwargs["task"], Path)


def test_task_file_controls_real_local_ingestion_csv_and_reexport(local_cli, tmp_path):
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps(
            [{"name": "Café 東京", "available": False}, {"name": "Other", "available": True}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "available": {"type": "boolean"}},
                "required": ["name", "available"],
            }
        ),
        encoding="utf-8",
    )
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps(
            {
                "dataset_sources": [{"url": source.as_uri(), "format": "json"}],
                "target_records": 2,
                "csv_mode": "json",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rows.json"
    result = local_cli.invoke(
        cli.app,
        [
            "run",
            "--goal",
            "Prepare declared rows",
            "--schema",
            str(schema),
            "--task",
            str(task),
            "--export",
            str(output),
            "--proof",
            "--no-animation",
        ],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert [{k: v for k, v in row.items() if k != "id"} for row in rows] == [
        {"name": "Café 東京", "available": False},
        {"name": "Other", "available": True},
    ]
    info = json.loads(output.with_suffix(".json.manifest.json").read_text(encoding="utf-8"))
    assert info["task"]["csv_mode"] == "json"
    assert info["task"]["target_records"] == 2
    assert info["model_request_units"] == 0
    assert info["search_attempts_reserved"] == {"openai": 0, "brave": 0}
    source.unlink()
    resumed = tmp_path / "resumed.json"
    again = local_cli.invoke(
        cli.app, ["run", "--resume", info["run_id"], "--export", str(resumed), "--no-animation"]
    )
    assert again.exit_code == 0, again.output
    assert json.loads(resumed.read_text(encoding="utf-8")) == rows


@pytest.mark.parametrize(
    "body",
    [None, "{", "[]", '{"csv_mode":"json","csv_mode":"spreadsheet"}', '{"unknown_option":true}'],
)
def test_invalid_task_is_controlled_and_does_not_create_a_ledger(local_cli, tmp_path, body):
    task = tmp_path / "bad-task.json"
    if body is not None:
        task.write_text(body, encoding="utf-8")
    result = local_cli.invoke(
        cli.app,
        [
            "run",
            "--goal",
            "Prepare rows",
            "--schema",
            "[name]",
            "--task",
            str(task),
            "--no-animation",
        ],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert not (tmp_path / "research.db").exists()


def test_task_file_cannot_be_overwritten_by_export(local_cli, tmp_path):
    task = tmp_path / "task.json"
    original = '{"csv_mode":"json"}'
    task.write_text(original, encoding="utf-8")
    result = local_cli.invoke(
        cli.app,
        [
            "run",
            "--goal",
            "Prepare rows",
            "--schema",
            "[name]",
            "--task",
            str(task),
            "--export",
            str(task),
            "--no-animation",
        ],
    )
    assert result.exit_code == 1
    assert task.read_text(encoding="utf-8") == original
    assert not (tmp_path / "research.db").exists()


def test_task_cannot_replace_saved_requirements_on_resume(local_cli, tmp_path):
    task = tmp_path / "task.json"
    task.write_text('{"csv_mode":"json"}', encoding="utf-8")
    result = local_cli.invoke(
        cli.app, ["run", "--resume", "not-a-run", "--task", str(task), "--no-animation"]
    )
    assert result.exit_code == 1
    assert "saved" in result.output.lower()
    assert not (tmp_path / "research.db").exists()


def test_task_and_column_flag_require_an_explicit_single_configuration(local_cli, tmp_path):
    task = tmp_path / "task.json"
    task.write_text('{"column_tables":[{"table":1}]}', encoding="utf-8")
    with patch.object(cli, "run") as call:
        result = local_cli.invoke(
            cli.app,
            [
                "run",
                "--goal",
                "Read table",
                "--schema",
                "[name]",
                "--task",
                str(task),
                "--column-table",
                "1",
                "--no-animation",
            ],
        )
    assert result.exit_code == 1
    assert "Choose --task or --column-table" in result.output
    call.assert_not_called()
