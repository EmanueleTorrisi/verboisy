"""Exercise the documented run subcommand and both forms of --resume."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import verboisy.cli.main as main
from typer.testing import CliRunner
from verboisy.api import RunResult

runner = CliRunner()


def result(tmp_path, completed=True, export_path=None):
    return RunResult(
        "saved-id",
        [],
        export_path,
        tmp_path / "db",
        completed,
        "COMPLETED" if completed else "PAUSED",
        None if completed else "max_steps",
    )


def test_help_is_a_group():
    invocation = runner.invoke(main.app, ["--help"])
    assert invocation.exit_code == 0 and "run" in invocation.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (["run", "--resume"], True),
        (["run", "-r"], True),
        (["run", "--resume", "--headed"], True),
        (["run", "--resume", "abc123"], "abc123"),
        (["run", "--resume=abc123"], "abc123"),
    ],
)
def test_resume_syntax(args, expected, monkeypatch, tmp_path):
    mock = Mock(return_value=result(tmp_path))
    monkeypatch.setattr(main, "run", mock)
    invocation = runner.invoke(main.app, args)
    assert invocation.exit_code == 0, invocation.output
    assert mock.call_args.kwargs["resume"] == expected


def test_documented_command_shape(monkeypatch, tmp_path):
    mock = Mock(return_value=result(tmp_path))
    monkeypatch.setattr(main, "run", mock)
    invocation = runner.invoke(
        main.app,
        [
            "run",
            "--goal",
            "Find names",
            "--schema",
            "schema.json",
            "--export",
            "result.csv",
            "--max-steps",
            "5",
            "--headed",
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert mock.call_args.kwargs["schema"] == Path("schema.json")
    assert mock.call_args.kwargs["max_steps"] == 5
    assert mock.call_args.kwargs["headless"] is False


def test_missing_inputs_fail():
    invocation = runner.invoke(main.app, ["run"])
    assert invocation.exit_code == 1 and "goal and schema" in invocation.output


def test_invalid_configuration_hides_secret(monkeypatch):
    monkeypatch.setenv("MAX_TOKENS", "secret-example")
    invocation = runner.invoke(main.app, ["run", "--resume"])
    assert invocation.exit_code == 1
    assert "secret-example" not in invocation.output


@pytest.mark.parametrize("completed,exit_code", [(True, 0), (False, 2)])
def test_completion_status_exit(monkeypatch, tmp_path, completed, exit_code):
    monkeypatch.setattr(main, "run", Mock(return_value=result(tmp_path, completed)))
    invocation = runner.invoke(main.app, ["run", "--resume"])
    assert invocation.exit_code == exit_code


def test_interrupt_exit(monkeypatch):
    monkeypatch.setattr(main, "run", Mock(side_effect=KeyboardInterrupt))
    invocation = runner.invoke(main.app, ["run", "--resume"])
    assert invocation.exit_code == 130 and "Committed records" in invocation.output


def test_failure_nonzero(monkeypatch):
    monkeypatch.setattr(main, "run", Mock(side_effect=RuntimeError("a secret")))
    invocation = runner.invoke(main.app, ["run", "--resume"])
    assert invocation.exit_code == 1 and "a secret" not in invocation.output


def test_invalid_max_steps():
    assert runner.invoke(main.app, ["run", "--max-steps", "0"]).exit_code == 2


def test_completed_run_displays_export_path(monkeypatch, tmp_path):
    """Display the export destination after a successful run."""
    export_path = tmp_path / "results.csv"

    mock = Mock(return_value=result(tmp_path, export_path=export_path))
    monkeypatch.setattr(main, "run", mock)

    invocation = runner.invoke(main.app, ["run", "--resume"])

    assert invocation.exit_code == 0, invocation.output
    assert "Exported to" in invocation.output
    assert str(export_path) in invocation.output
    assert "Completed" in invocation.output

    mock.assert_called_once()
