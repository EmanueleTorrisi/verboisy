# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved status is coherent, run-scoped and read-only for every run type."""

import json
import sqlite3
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import TaskSpec
from verboisy.storage.diagnostics import inspect_research_status
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage import test_repair_inspection as repairs


@pytest.fixture
def ledger(tmp_path):
    yield from repairs.ledger.__wrapped__(tmp_path)


def test_saved_counts_and_journal_accounting_during_writer_lock(ledger):
    path, store, rid = ledger
    store.finish(rid, "FAILED", "LLM request failed (HTTP 400)", 17, 796)
    store.event(
        rid,
        "search_request",
        {"status": "reserved", "attempt_id": "attempt-1", "secret": "PRIVATE"},
    )
    store.event(rid, "search_request", {"status": "reserved", "attempt_id": "attempt-1"})
    store.event(rid, "search_request", {"status": "failed", "attempt_id": "attempt-1"})
    store.event(rid, "coverage_gap", {"secret": "PRIVATE"})
    store.db.execute("INSERT INTO candidates(run_id,accepted,payload) VALUES (?,0,'{}')", (rid,))
    other = store.create("Other", {}, TaskSpec(), None)
    store.event(other, "search_request", {"status": "reserved", "attempt_id": "other"})
    store.db.commit()
    files = {p.name for p in path.parent.iterdir()}
    before = path.read_bytes()
    events = store.events(rid)
    with patch(
        "verboisy.core.research.ResearchRunner.run", side_effect=AssertionError("execution")
    ):
        report = inspect_research_status(path, rid)
    assert report["status"] == "FAILED"
    assert report["stop_reason"] == "LLM request failed (HTTP 400)"
    assert report["counts"] == {
        "accepted_records": 2,
        "candidates": 3,
        "rejected_candidates": 1,
        "snapshots": 2,
        "dataset_assets": 1,
        "events": len(events),
        "identity_conflicts": 0,
        "coverage_gap_events": 1,
    }
    assert report["page_outcomes"] == {"queued": 1}
    assert report["request_accounting"] == {
        "reported_tokens": 17,
        "reserved_request_units": 796,
        "journaled_search_attempts": 1,
    }
    assert "PRIVATE" not in json.dumps(report)
    assert store.events(rid) == events
    assert path.read_bytes() == before
    assert {p.name for p in path.parent.iterdir()} == files


@pytest.mark.parametrize("status", ["FAILED", "PAUSED", "COMPLETED"])
def test_browser_only_empty_run_is_inspectable(tmp_path, status):
    path = tmp_path / "browser.db"
    store = ResearchStore(str(path))
    rid = store.create("Browser only", {}, TaskSpec(), None)
    store.finish(rid, status, "fixture", 0, 0)
    store.close()
    report = inspect_research_status(path, rid)
    assert report["status"] == status
    assert report["counts"]["accepted_records"] == 0
    assert report["page_outcomes"] == {}
    assert report["request_accounting"]["journaled_search_attempts"] == 0


def test_cli_default_and_explicit_database(ledger, monkeypatch):
    path, _, rid = ledger
    monkeypatch.setenv("SQLITE_DB_PATH", str(path))
    cli = CliRunner()
    expected = inspect_research_status(path, rid)
    for arguments in [
        ["status", "--run-id", rid],
        ["status", "--run-id", rid, "--database", str(path)],
    ]:
        result = cli.invoke(app, arguments)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == expected


def test_unknown_run_and_missing_database_do_not_create_work(ledger, tmp_path):
    path, _, _ = ledger
    with pytest.raises(VerboisyError, match="No saved research run"):
        inspect_research_status(path, "missing")
    missing = tmp_path / "missing.db"
    result = CliRunner().invoke(app, ["status", "--run-id", "missing", "--database", str(missing)])
    assert result.exit_code == 1
    assert not missing.exists()
    assert not missing.with_name("missing.db.lock").exists()


def test_invalid_search_journal_is_reported_without_mutation(ledger):
    path, store, rid = ledger
    store.db.execute(
        "INSERT INTO events(run_id,kind,payload) VALUES (?,'search_request','[]')", (rid,)
    )
    store.db.commit()
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="invalid run status context"):
        inspect_research_status(path, rid)
    assert path.read_bytes() == before


def test_old_ledger_is_not_migrated(tmp_path):
    path = tmp_path / "old.db"
    ResearchStore(str(path)).close()
    db = sqlite3.connect(path)
    db.execute("UPDATE research_meta SET version=3")
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="current ledger version"):
        inspect_research_status(path, "missing")
    assert path.read_bytes() == before


def test_invalid_active_config_error_does_not_echo_input(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_LIMIT_PARAMETER", "PRIVATE_INVALID")
    result = CliRunner().invoke(app, ["status", "--run-id", "any"])
    assert result.exit_code == 1
    assert "llm_token_limit_parameter" in result.output
    assert "PRIVATE_INVALID" not in result.output


@pytest.mark.parametrize("run_id", ["", "  ", None, 0])
def test_empty_or_invalid_id_does_not_select_latest_or_open_database(tmp_path, run_id):
    path = tmp_path / "absent.db"
    with pytest.raises(VerboisyError, match="nonempty saved run ID"):
        inspect_research_status(path, run_id)
    assert not list(tmp_path.iterdir())
