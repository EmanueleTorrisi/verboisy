# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Preparation reports its result before exit 2; read-only status still exits zero."""

import json

from typer.testing import CliRunner
from verboisy.cli.main import app


def test_pause_status_and_complete_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASET_LOCAL_ROOTS", json.dumps([str(tmp_path)]))
    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n{"n":2}\n')
    runner = CliRunner()
    paused = runner.invoke(
        app,
        [
            "stream",
            "--database",
            str(tmp_path / "stream.db"),
            "--dataset-file",
            "jsonl=" + str(source),
            "--rows-per-invocation",
            "1",
        ],
    )
    assert paused.exit_code == 2
    result = json.loads(paused.output)
    status = runner.invoke(app, ["stream-status", "--database", str(tmp_path / "stream.db")])
    assert status.exit_code == 0 and json.loads(status.output)["jobs"][0]["status"] == "PAUSED"
    complete = runner.invoke(
        app, ["stream", "--database", str(tmp_path / "stream.db"), "--resume", result["job_id"]]
    )
    assert complete.exit_code == 0 and json.loads(complete.output)["status"] == "COMPLETED"


def test_interruption_exit_130(monkeypatch):
    import verboisy.cli.streaming as commands

    def interrupt(**_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(commands, "stream_dataset", interrupt)
    result = CliRunner().invoke(app, ["stream", "--dataset-file", "jsonl=synthetic"])
    assert result.exit_code == 130


def test_invalid_projection_does_not_echo_configuration_value(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text('{"fields":[{"source":"/n","target":"/n","conversion":"private-invalid"}]}')
    result = CliRunner().invoke(
        app, ["stream", "--projection", str(plan), "--dataset-file", "jsonl=synthetic"]
    )
    assert result.exit_code == 1 and "Invalid streaming configuration fields" in result.output
    assert "private-invalid" not in result.output


def test_interrupted_saved_result_prints_json_then_exits_130(tmp_path, monkeypatch):
    import verboisy.streaming.api as api

    monkeypatch.setenv("DATASET_LOCAL_ROOTS", json.dumps([str(tmp_path)]))
    source = tmp_path / "source.jsonl"
    source.write_text('{"n":1}\n')

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(api, "_commit", interrupt)
    result = CliRunner().invoke(
        app,
        [
            "stream",
            "--database",
            str(tmp_path / "stream.db"),
            "--dataset-file",
            "jsonl=" + str(source),
        ],
    )
    assert result.exit_code == 130
    saved = json.loads(result.output)
    assert (
        saved["status"] == "PAUSED"
        and saved["reason"] == "interrupted"
        and saved["processed_rows"] == 0
    )
