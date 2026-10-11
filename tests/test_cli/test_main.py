# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from __future__ import annotations

from pathlib import Path
from typing import Any

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
        ["run", "--goal", "x", "--schema", "[name]", "--orderby=name", "--orderbydesc=age"],
    )
    assert result.exit_code == 0
    assert [(key.field, key.direction) for key in captured["order"]] == [
        ("name", "asc"),
        ("age", "desc"),
    ]
    assert "Grouping by country." in result.output
    assert "Dataset:" in result.output
    assert "Manifest:" in result.output
    assert "Proof:" in result.output


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
    assert "OpenAI rate limit reached" in response.output
    assert "Research progress was saved" in response.output
    assert "verboisy run --resume" in response.output
    assert "Dataset:" not in response.output
    assert "Manifest:" not in response.output
    assert "Proof:" not in response.output
