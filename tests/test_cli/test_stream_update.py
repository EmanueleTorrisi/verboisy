# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import json
import subprocess
import sys
from pathlib import Path

import verboisy
import verboisy.streaming as streaming
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.utils.config import Settings


def test_cli_writes_an_incremental_patch_and_requires_explicit_deletion(tmp_path):
    database = tmp_path / "stream.db"
    config = Settings(_env_file=None, dataset_local_roots=[str(tmp_path)])
    ids = []
    for name, content in (
        ("old", b'{"id":"a","value":1}\n{"id":"b","value":2}\n'),
        ("new", b'{"id":"a","value":3}\n{"id":"c","value":4}\n'),
    ):
        source = tmp_path / f"{name}.jsonl"
        source.write_bytes(content)
        result = streaming.stream_dataset(
            database=database, source=source, dataset_format="jsonl", config=config
        )
        assert result.status == "COMPLETED"
        ids.append(result.job_id)
    command = [
        "stream-update",
        "--database",
        str(database),
        "--baseline",
        ids[0],
        "--current",
        ids[1],
        "--key",
        "/id",
    ]
    output = tmp_path / "retain.jsonl"
    runner = CliRunner()
    result = runner.invoke(app, [*command, "--export", str(output)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert (report["inserted"], report["updated"], report["removed"], report["unobserved"]) == (
        1,
        1,
        0,
        1,
    )
    assert output.is_file()
    output = tmp_path / "complete.jsonl"
    result = runner.invoke(app, [*command, "--export", str(output), "--complete-snapshot"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["removed"] == 1
    assert output.is_file()
    denied = runner.invoke(app, [*command, "--export", str(output)])
    assert denied.exit_code == 1 and "new .jsonl" in denied.stderr


def test_interrupted_update_has_conventional_exit_status(tmp_path, monkeypatch):
    def interrupted(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(streaming, "stream_updates", interrupted)
    output = tmp_path / "changes.jsonl"
    result = CliRunner().invoke(
        app,
        [
            "stream-update",
            "--baseline",
            "old",
            "--current",
            "new",
            "--key",
            "/id",
            "--export",
            str(output),
        ],
    )
    assert result.exit_code == 130
    assert not output.exists()


def test_update_help_does_not_import_the_streaming_runtime():
    package = Path(verboisy.__file__).resolve().parents[1]
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from typer.testing import CliRunner
from verboisy.cli.main import app
result = CliRunner().invoke(app, ["stream-update", "--help"])
assert result.exit_code == 0, result.output
assert "streaming job ID" in result.output
assert "verboisy.streaming.update" not in sys.modules
assert "verboisy.streaming.delta" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code, str(package)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
