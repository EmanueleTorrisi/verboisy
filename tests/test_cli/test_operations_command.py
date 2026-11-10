# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The operations command writes data on stdout and refusals on stderr."""

import json
from contextlib import closing
from unittest.mock import Mock

import verboisy
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.streaming.ledger import StreamLedger


def test_report_cli_writes_versioned_json_and_controlled_errors(tmp_path, monkeypatch):
    path = tmp_path / "stream.db"
    with closing(StreamLedger(path)):
        pass
    runner = CliRunner()
    args = ["report", "--database", str(path), "--kind", "stream"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["report_version"] == "operations-1" and report["run_count"] == 0
    assert report["ledger_kind"] == "stream" and str(path) not in result.stdout

    bad = runner.invoke(app, [*args, "--limit", "0"])
    assert bad.exit_code == 1 and not bad.stdout and "report limit" in bad.stderr
    stop = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(verboisy, "operational_report", stop)
    interrupted = runner.invoke(app, args)
    assert interrupted.exit_code == 130 and not interrupted.stdout
    stop.assert_called_once_with(path, kind="stream", run_id=None, limit=100)
