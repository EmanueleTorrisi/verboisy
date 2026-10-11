# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run discovery is bounded, coherent and read-only, with honest declaration labels."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import TaskSpec
from verboisy.storage.diagnostics import inspect_research_runs
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


def test_inventory_during_writer_lock_with_mixed_tasks_and_limits(tmp_path):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    try:
        browser = store.create("Browser", {}, TaskSpec(), None)
        dataset = store.create(
            "Données",
            {},
            TaskSpec(dataset_sources=[{"url": "https://example.test/data.csv", "format": "csv"}]),
            None,
        )
        store.finish(dataset, "FAILED", "fixture_failure", 0, 0)
        bad = store.create("Broken", {}, TaskSpec(), None)
        store.db.execute("UPDATE research_runs SET task_json=? WHERE id=?", ("{", bad))
        store.db.commit()
        files = {p.name for p in tmp_path.iterdir()}
        original = path.read_bytes()
        with patch("verboisy.core.research.ResearchRunner", side_effect=AssertionError):
            report = inspect_research_runs(path, limit=2)
            assert report["truncated"] is True
            assert report["database"] == str(path.resolve())
            assert [r["run_id"] for r in report["runs"]] == [bad, dataset]
            assert report["runs"][0]["repair_inspection"] == "invalid_task"
            assert report["runs"][0]["dataset_source_count"] is None
            assert report["runs"][1] == {
                "run_id": dataset,
                "goal": "Données",
                "status": "FAILED",
                "stop_reason": "fixture_failure",
                "dataset_source_count": 1,
                "repair_inspection": "available",
            }
            all_runs = inspect_research_runs(path, limit=3)
            assert all_runs["truncated"] is False
            assert all_runs["runs"][2]["run_id"] == browser
            assert all_runs["runs"][2]["repair_inspection"] == "no_dataset_sources"
        assert path.read_bytes() == original
        assert {p.name for p in tmp_path.iterdir()} == files
    finally:
        store.close()


def test_empty_inventory(tmp_path):
    path = tmp_path / "empty.db"
    ResearchStore(str(path)).close()
    report = inspect_research_runs(path)
    assert report["runs"] == []
    assert report["truncated"] is False


@pytest.mark.parametrize("limit", [True, "3", 0, -1, 1001])
def test_invalid_limits_do_not_create_database(tmp_path, limit):
    path = tmp_path / "absent.db"
    with pytest.raises(VerboisyError, match="limit"):
        inspect_research_runs(path, limit=limit)
    assert not list(tmp_path.iterdir())


def test_cli_configured_database_and_explicit_override(tmp_path, monkeypatch):
    configured = tmp_path / "configured.db"
    override = tmp_path / "override.db"
    ResearchStore(str(configured)).close()
    store = ResearchStore(str(override))
    rid = store.create("Override", {}, TaskSpec(), None)
    store.close()
    monkeypatch.setenv("SQLITE_DB_PATH", str(configured))
    cli = CliRunner()
    result = cli.invoke(app, ["runs"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["runs"] == []
    result = cli.invoke(app, ["runs", "--database", str(override), "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["runs"][0]["run_id"] == rid


def test_cli_missing_database_does_not_create_files(tmp_path):
    result = CliRunner().invoke(app, ["runs", "--database", str(tmp_path / "absent.db")])
    assert result.exit_code == 1
    assert "existing research database" in result.output
    assert not list(tmp_path.iterdir())


def test_partial_current_ledger_reports_error_without_changes(tmp_path):
    path = tmp_path / "partial.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE research_meta(version INTEGER)")
    db.execute("INSERT INTO research_meta VALUES (4)")
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="invalid run inventory"):
        inspect_research_runs(path)
    assert path.read_bytes() == before
    assert not Path(str(path) + ".lock").exists()


def test_old_ledger_remains_unmigrated(tmp_path):
    path = tmp_path / "old.db"
    ResearchStore(str(path)).close()
    db = sqlite3.connect(path)
    db.execute("UPDATE research_meta SET version=3")
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="current ledger version"):
        inspect_research_runs(path)
    assert path.read_bytes() == before
