# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The CLI distinguishes verified contract failures from execution errors."""

import json
import subprocess
import sys
from pathlib import Path

import verboisy
import verboisy.streaming as streaming
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.utils.config import Settings


def test_quality_command_reports_pass_and_verified_rule_failure(tmp_path):
    database = tmp_path / "stream.db"
    source = tmp_path / "data.jsonl"
    source.write_bytes(b'{"id":1,"value":"private"}\n{"id":2,"value":null}\n')
    job = streaming.stream_dataset(
        database=database,
        source=source,
        dataset_format="jsonl",
        config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    assert job.status == "COMPLETED"
    rule = tmp_path / "quality.json"
    command = [
        "stream-quality",
        "--database",
        str(database),
        "--job",
        job.job_id,
        "--contract",
        str(rule),
        "--max-index-bytes",
        "65536",
        "--scratch-dir",
        str(tmp_path),
    ]
    runner = CliRunner()
    contract = {
        "version": "1",
        "min_rows": 2,
        "completeness": [{"field": "/value", "min_present_percent": 50}],
        "unique": [["/id"]],
    }
    rule.write_bytes(json.dumps(contract).encode())
    passed = runner.invoke(app, command)
    assert passed.exit_code == 0, passed.output
    assert json.loads(passed.stdout)["passed"]
    contract["completeness"][0]["min_present_percent"] = 100
    rule.write_bytes(json.dumps(contract).encode())
    failed = runner.invoke(app, command)
    assert failed.exit_code == 3, failed.output
    report = json.loads(failed.stdout)
    assert not report["passed"] and report["completeness"][0]["null"] == 1
    assert "private" not in failed.stdout


def test_quality_command_rejects_malformed_contract_without_a_report(tmp_path):
    rule = tmp_path / "invalid.json"
    rule.write_bytes(b'{"version":"1","min_rows":2,"min_rows":1}')
    result = CliRunner().invoke(
        app, ["stream-quality", "--job", "unknown", "--contract", str(rule)]
    )
    assert result.exit_code == 1 and not result.stdout
    assert "Error:" in result.stderr and "Traceback" not in result.stderr


def test_quality_command_interrupt_has_conventional_exit_status(tmp_path, monkeypatch):
    def interrupted(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(streaming, "check_stream_quality", interrupted)
    rule = tmp_path / "quality.json"
    rule.write_bytes(b'{"version":"1"}')
    result = CliRunner().invoke(app, ["stream-quality", "--job", "test", "--contract", str(rule)])
    assert result.exit_code == 130 and not result.stdout


def test_quality_help_does_not_load_replay_or_create_an_index():
    package = Path(verboisy.__file__).resolve().parents[1]
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from typer.testing import CliRunner
from verboisy.cli.main import app
result = CliRunner().invoke(app, ["stream-quality", "--help"])
assert result.exit_code == 0, result.output
assert "verboisy.streaming.quality" not in sys.modules
assert "verboisy.streaming.quality_checks" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code, str(package)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
