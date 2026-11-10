# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verify the registered CLI contract and controlled failures."""

import gzip
import json
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner
from verboisy import streaming
from verboisy.cli.main import app
from verboisy.streaming import AnalyticalExport, stream_dataset
from verboisy.utils.config import Settings


def test_cli_exports_a_completed_job(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_bytes(b'{"id":1}\n{"id":2}\n')
    database = tmp_path / "stream.db"
    job = stream_dataset(
        database=database,
        source=source,
        dataset_format="jsonl",
        config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    assert job.status == "COMPLETED", job.reason
    output = tmp_path / "bundle"
    result = CliRunner().invoke(
        app,
        [
            "stream-analytics",
            "--database",
            str(database),
            "--job",
            job.job_id,
            "--output-dir",
            str(output),
            "--shard-rows",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["rows"] == receipt["shards"] == 2
    assert Path(receipt["manifest"]) == output / "manifest.json"
    assert gzip.decompress((output / "part-00001.jsonl.gz").read_bytes()) == b'{"id":2}\n'


def test_cli_accepts_strict_columns_and_stops_on_bad_file_or_interrupt(tmp_path, monkeypatch):
    column_file = tmp_path / "columns.json"
    contract = {"version": "1", "columns": [{"name": "id", "type": "int64", "nullable": False}]}
    output = tmp_path / "bundle"
    implementation = Mock(return_value=AnalyticalExport(output / "manifest.json", 2, 1, 3))
    monkeypatch.setattr(streaming, "export_stream_analytics", implementation)
    args = [
        "stream-analytics",
        "--job",
        "saved",
        "--output-dir",
        str(output),
        "--format",
        "parquet",
        "--columns",
        str(column_file),
    ]
    column_file.write_text('{"version":"1","version":"1"}', encoding="utf-8")
    runner = CliRunner()
    rejected = runner.invoke(app, args)
    assert rejected.exit_code == 1 and "Invalid finite unique UTF-8 JSON" in rejected.stderr
    implementation.assert_not_called()
    column_file.write_text(json.dumps(contract), encoding="utf-8")
    assert runner.invoke(app, args).exit_code == 0
    assert implementation.call_args.kwargs["column_contract"] == contract
    implementation.side_effect = KeyboardInterrupt
    stopped = runner.invoke(app, args)
    assert stopped.exit_code == 130 and not output.exists()
