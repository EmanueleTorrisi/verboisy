# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import verboisy.cli.main as cli
from typer.testing import CliRunner
from verboisy.api import RunResult

runner = CliRunner()


def completed_result(tmp_path: Path) -> RunResult:
    return RunResult(
        run_id="run-1",
        records=[{"id": "row-1", "name": "A"}],
        export_path=None,
        db_path=tmp_path / "runs.db",
        completed=True,
        status="COMPLETED",
        stop_reason="target_met",
    )


def test_run_help_explains_simple_schema_and_product_options():
    result = runner.invoke(cli.app, ["run", "--help"])
    assert result.exit_code == 0
    assert "[name,price,...]" in result.output
    assert "--onlyinclude" in result.output
    assert "--smartid" in result.output
    assert "--proof" in result.output
    assert "--no-animation" in result.output


def test_cli_preserves_mixed_sort_argument_order(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> RunResult:
        captured.update(kwargs)
        return completed_result(tmp_path)

    monkeypatch.setattr(cli, "run", fake_run)
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--goal",
            "Find athletes",
            "--schema",
            "[name,age,height]",
            "--orderby",
            "age",
            "--orderbydesc",
            "height",
            "--orderby",
            "name",
        ],
    )
    assert result.exit_code == 0
    assert [(key.field, key.direction) for key in captured["order"]] == [
        ("age", "asc"),
        ("height", "desc"),
        ("name", "asc"),
    ]


def test_cli_bare_resume_is_normalized(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> RunResult:
        captured.update(kwargs)
        return completed_result(tmp_path)

    monkeypatch.setattr(cli, "run", fake_run)
    result = runner.invoke(cli.app, ["run", "--resume"])
    assert result.exit_code == 0
    assert captured["resume"] is True


def test_cli_equals_sort_syntax_and_result_artifacts(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> RunResult:
        captured.update(kwargs)
        return RunResult(
            run_id="run-2",
            records=[],
            export_path=tmp_path / "out.csv",
            db_path=tmp_path / "runs.db",
            completed=True,
            status="COMPLETED",
            stop_reason="target_met",
            export_paths=(tmp_path / "out.csv",),
            manifest_paths=(tmp_path / "out.csv.manifest.json",),
            proof_path=tmp_path / "out.proof.txt",
            notices=("Grouping by country.",),
        )

    monkeypatch.setattr(cli, "run", fake_run)
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--goal",
            "x",
            "--schema",
            "[name]",
            "--orderby=name",
            "--orderbydesc=age",
            "--verbose",
        ],
    )
    assert result.exit_code == 0
    assert [(key.field, key.direction) for key in captured["order"]] == [
        ("name", "asc"),
        ("age", "desc"),
    ]
    assert "Grouping by country." in result.output
    assert "CSV:" in result.output
    assert "Manifest:" in result.output
    assert "Proof:" in result.output


def test_cli_clean_layout_uses_started_identity_and_keeps_manifests_optional(monkeypatch, tmp_path):
    def fake_run(**kwargs: Any) -> RunResult:
        kwargs["on_started"]("persisted-id", "Saved research goal")
        return RunResult(
            run_id="persisted-id",
            records=[{"id": 1, "name": "A", "price": 2.5}],
            export_path=tmp_path / "out.csv",
            db_path=tmp_path / "run.db",
            completed=True,
            status="COMPLETED",
            stop_reason="target_met",
            export_paths=(tmp_path / "out.csv", tmp_path / "out.json"),
            manifest_paths=(tmp_path / "out.csv.manifest.json",),
            proof_path=tmp_path / "out.proof.txt",
        )

    monkeypatch.setattr(cli, "run", fake_run)
    result = runner.invoke(cli.app, ["run", "--resume"])
    assert result.exit_code == 0, result.output
    output = result.output
    assert output.count("Run ID:") == 1 and "✦ Saved research goal" in output
    assert "Status: COMPLETED" in output and "Success: Completed" not in output
    assert "CSV preview: first 1 of 1 rows." in output
    assert "JSON preview: first 1 of 1 rows; 2 of 2 source columns." in output
    assert "CSV:" in output and "JSON:" in output and "Proof:" in output
    assert "Manifest:" not in output and "Task:" not in output
    assert output.index("Run ID:") < output.index("Status:") < output.index("CSV preview:")
    assert output.index("JSON preview:") < output.index("→    CSV:")


@pytest.mark.parametrize(
    "error,status,code",
    [
        (KeyboardInterrupt(), "INTERRUPTED", 130),
        (OSError("disk"), "FAILED", 1),
        (RuntimeError("internal"), "FAILED", 1),
    ],
)
def test_cli_exception_closes_status_without_claiming_completion(monkeypatch, error, status, code):
    def fake_run(**kwargs: Any) -> RunResult:
        kwargs["on_started"]("saved-before-error", "Research")
        raise error

    monkeypatch.setattr(cli, "run", fake_run)
    result = runner.invoke(cli.app, ["run", "--goal", "x", "--schema", "[name]"])
    assert result.exit_code == code
    assert f"Status: {status}" in result.output
    assert "COMPLETED" not in result.output and "Thank you" not in result.output


def test_cli_reports_provider_rate_limit(monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner
    from verboisy.cli.main import app

    result = SimpleNamespace(
        run_id="run-rate-limit",
        status="PAUSED",
        records=[],
        notices=(),
        export_paths=("/tmp/partial.json",),
        manifest_paths=("/tmp/partial.json.manifest.json",),
        proof_path="/tmp/partial.proof.txt",
        completed=False,
        stop_reason="provider_rate_limit",
    )

    monkeypatch.setattr(
        "verboisy.cli.main.Settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "verboisy.cli.main.setup_logging",
        lambda _config: None,
    )
    monkeypatch.setattr(
        "verboisy.cli.main.run",
        lambda **_kwargs: result,
    )

    response = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Find records",
            "--schema",
            "[name]",
        ],
    )

    assert response.exit_code == 2
    assert "Provider rate limit reached" in response.output
    assert "Research progress was saved" in response.output
    assert "verboisy run --resume" in response.output
    assert "Dataset:" not in response.output
    assert "Manifest:" not in response.output
    assert "Proof:" not in response.output


@pytest.mark.parametrize("command", ["doctor", "runs", "setup"])
def test_malformed_settings_use_field_only_diagnostics(monkeypatch, command):
    monkeypatch.setenv("MAX_STEPS", "private-invalid-value")
    result = CliRunner().invoke(cli.app, [command])
    assert result.exit_code == 1 and "Invalid configuration fields" in result.output
    assert "private-invalid-value" not in result.output


def test_no_animation_option_reaches_run_display(monkeypatch, tmp_path):
    options = []
    original = cli.RunDisplay

    class ObservedDisplay(original):
        def __init__(self, *, animate=False):
            options.append(animate)
            super().__init__(animate=animate)

    monkeypatch.setattr(cli, "RunDisplay", ObservedDisplay)
    monkeypatch.setattr(cli, "run", lambda **_kwargs: completed_result(tmp_path))
    result = runner.invoke(cli.app, ["run", "--goal", "x", "--schema", "[name]", "--no-animation"])
    assert result.exit_code == 0, result.output
    assert options == [False]


@pytest.mark.parametrize("presentation", ["print_header", "print_signoff"])
def test_interrupt_during_presentation_does_not_repeat_research(
    monkeypatch, tmp_path, presentation
):
    calls = []

    def actual_run(**_kwargs):
        calls.append("run")
        return completed_result(tmp_path)

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run", actual_run)
    monkeypatch.setattr(cli.CLIUserInterface, presentation, interrupt)
    result = runner.invoke(cli.app, ["run", "--goal", "x", "--schema", "[name]"])
    assert result.exit_code == 130
    assert "Display interrupted" in result.output
    assert len(calls) == (1 if presentation == "print_signoff" else 0)
