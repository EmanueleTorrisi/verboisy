# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The CLI exposes explicit retention and private report admission."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import verboisy
from typer.testing import CliRunner
from verboisy import retention, workspace
from verboisy.cli.main import app
from verboisy.utils.exceptions import VerboisyError


def test_retention_cli_previews_and_applies_only_when_requested(tmp_path, monkeypatch):
    command = Mock(return_value={"applied": False, "plan_sha256": "1" * 64})
    monkeypatch.setattr(retention, "retain_completed", command)
    runner = CliRunner()
    args = ["retention", "--workspace", str(tmp_path), "--database", "jobs.db"]
    preview = runner.invoke(app, args)
    assert preview.exit_code == 0 and not preview.stderr, preview.output
    assert json.loads(preview.stdout) == command.return_value
    command.assert_called_once_with(
        tmp_path, "jobs.db", kind="research", keep_last=10, limit=25, protect=(), apply_plan=None
    )

    command.reset_mock(return_value=True)
    command.return_value = {"applied": True}
    applied = runner.invoke(
        app,
        [
            *args,
            "--kind",
            "stream",
            "--keep-last",
            "2",
            "--limit",
            "3",
            "--protect-run-id",
            "a" * 32,
            "--protect-run-id",
            "b" * 32,
            "--apply-plan",
            "1" * 64,
        ],
    )
    assert applied.exit_code == 0 and json.loads(applied.stdout)["applied"], applied.output
    command.assert_called_once_with(
        tmp_path,
        "jobs.db",
        kind="stream",
        keep_last=2,
        limit=3,
        protect=("a" * 32, "b" * 32),
        apply_plan="1" * 64,
    )


def test_retention_cli_refusal_and_interruption(tmp_path, monkeypatch):
    command = Mock(side_effect=VerboisyError("Retention plan changed"))
    monkeypatch.setattr(retention, "retain_completed", command)
    args = ["retention", "--workspace", str(tmp_path), "--database", "jobs.db"]
    runner = CliRunner()
    refused = runner.invoke(app, args)
    assert refused.exit_code == 1 and not refused.stdout
    assert refused.stderr.strip() == "Error: Retention plan changed"
    command.side_effect = KeyboardInterrupt
    interrupted = runner.invoke(app, args)
    assert interrupted.exit_code == 130 and not interrupted.stdout


def test_private_report_checks_workspace_before_opening_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "jobs.db"
    guard = Mock(return_value=SimpleNamespace(path=ledger))
    report = Mock(return_value={"report_version": "operations-1"})
    monkeypatch.setattr(workspace, "workspace_ledger", guard)
    monkeypatch.setattr(verboisy, "operational_report", report)
    args = ["report", "--workspace", str(tmp_path), "--database", ledger.name, "--kind", "stream"]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0 and json.loads(result.stdout) == report.return_value
    guard.assert_called_once_with(tmp_path, ledger.name)
    report.assert_called_once_with(ledger, kind="stream", run_id=None, limit=100)

    report.reset_mock()
    guard.side_effect = VerboisyError("Workspace must be an owned directory with mode 0700")
    refused = runner.invoke(app, args)
    assert refused.exit_code == 1 and not refused.stdout and "mode 0700" in refused.stderr
    report.assert_not_called()
