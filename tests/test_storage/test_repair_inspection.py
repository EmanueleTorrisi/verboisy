# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved repair inspection is coherent, verified, bounded and SQLite-enforced read-only."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.extractor.ingestion import row_evidence
from verboisy.storage.assets import DatasetAssetError
from verboisy.storage.diagnostics import inspect_dataset_repairs
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_research import test_dataset_metadata_refresh as metadata
from tests.test_research import test_temporal_projection_ingestion as temporal
from tests.test_storage.test_dataset_assets import capture


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "run.db"
    store = ResearchStore(str(path))
    plan = metadata.missing_plan("unit")
    task = TaskSpec(
        identity_fields=["/name"],
        dataset_sources=[
            {"url": "https://example.test/start", "format": "json", "projection": plan}
        ],
    )
    rid = store.create("Latest population", temporal.schema(True, True), task, None)
    raw = [{**temporal.rows()[0], "name": name, "amount": "2000"} for name in ("A", "B")]
    aid = store.save_dataset_asset(rid, capture(json.dumps(raw).encode(), "json"))
    asset = store.load_dataset_asset(rid, aid)
    for row in asset.download.dataset.rows:
        page, candidate = row_evidence(asset, row, ProjectionPlan.model_validate(plan))
        store.queue(rid, page.url, 0, None)
        work = store.db.execute(
            "SELECT id FROM pages WHERE run_id=? AND url=?", (rid, page.url)
        ).fetchone()
        store.snapshot(rid, work[0], page, "fixture")
        assert store.accept(rid, page, candidate, [], task) == "accepted"
    store.finish(rid, "PAUSED", "dataset_consistency_gaps", 0, 0)
    try:
        yield path, store, rid
    finally:
        store.close()


def test_inspection_works_during_writer_lock_without_calls_or_mutations(ledger):
    path, store, rid = ledger
    before = store.events(rid)
    files = {p.name for p in path.parent.iterdir()}
    database_bytes = path.read_bytes()
    with (
        patch(
            "verboisy.core.research.ResearchRunner.run",
            side_effect=AssertionError("runner executed"),
        ),
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            side_effect=AssertionError("model executed"),
        ),
        patch(
            "verboisy.browser.context.BrowserManager.start",
            side_effect=AssertionError("browser started"),
        ),
    ):
        report = inspect_dataset_repairs(path, rid, limit=1)
    assert report["run_id"] == rid and report["status"] == "PAUSED"
    assert report["gaps"] == ["/population:unknown_unit"]
    assert report["repair_count"] == 2 and report["truncated"]
    assert len(report["repairs"]) == 1 and report["scope"] == "accepted_records"
    repair = report["repairs"][0]
    assert repair["record_id"] == store.evidence(rid)[0]["record_id"]
    assert repair["snapshot_id"] == store.evidence(rid)[0]["snapshot"]["id"]
    assert store.events(rid) == before and path.read_bytes() == database_bytes
    assert {p.name for p in path.parent.iterdir()} == files
    full = inspect_dataset_repairs(path, rid, limit=2)
    assert len(full["repairs"]) == 2 and not full["truncated"]


def test_read_only_connection_denies_journal_and_run_updates(ledger):
    path, store, rid = ledger
    reader = ResearchStore(str(path), read_only=True)
    try:
        assert reader.load(rid)["status"] == "PAUSED"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.event(rid, "forbidden", {})
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.finish(rid, "COMPLETED", "forbidden", 0, 0)
    finally:
        reader.close()
    assert store.events(rid, "forbidden") == []


@pytest.mark.parametrize("limit", [True, "3", 0, -1, 1001])
def test_invalid_limit_never_creates_a_database(tmp_path, limit):
    path = tmp_path / "missing.db"
    with pytest.raises(VerboisyError, match="limit"):
        inspect_dataset_repairs(path, "none", limit=limit)
    assert not path.exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_read_only_requires_existing_regular_database(tmp_path, kind):
    path = tmp_path / "db"
    if kind == "directory":
        path.mkdir()
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"fixture")
        path.symlink_to(target)
    with pytest.raises(VerboisyError, match="existing"):
        ResearchStore(str(path), read_only=True)
    assert not Path(str(path.resolve()) + ".lock").exists()


@pytest.mark.parametrize("kind", ["empty", "old", "duplicate", "partial"])
def test_inspection_does_not_initialize_or_migrate(tmp_path, kind):
    path = tmp_path / "run.db"
    db = sqlite3.connect(path)
    if kind != "empty":
        db.execute("CREATE TABLE research_meta(version INTEGER)")
        db.execute("INSERT INTO research_meta VALUES(?)", (3 if kind == "old" else 4,))
        if kind == "duplicate":
            db.execute("INSERT INTO research_meta VALUES(4)")
    db.commit()
    db.close()
    original = path.read_bytes()
    with pytest.raises(VerboisyError, match="ledger|database version"):
        inspect_dataset_repairs(path, "none")
    assert path.read_bytes() == original
    assert not Path(str(path) + ".lock").exists()


def test_read_only_connection_failure_is_explained(tmp_path):
    path = tmp_path / "run.db"
    path.write_bytes(b"fixture")
    with (
        patch(
            "verboisy.storage.research.sqlite3.connect",
            side_effect=sqlite3.OperationalError("fixture"),
        ),
        pytest.raises(VerboisyError, match="Cannot open"),
    ):
        ResearchStore(str(path), read_only=True)


def test_repair_inspection_translates_saved_context_failure_and_closes(ledger, monkeypatch):
    path, _, rid = ledger
    opened = []
    original = ResearchStore

    def remember(*args, **kwargs):
        store = original(*args, **kwargs)
        opened.append(store)
        return store

    monkeypatch.setattr("verboisy.storage.diagnostics.ResearchStore", remember)
    monkeypatch.setattr(original, "load", lambda *_args: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(VerboisyError, match="invalid dataset repair context"):
        inspect_dataset_repairs(path, rid)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].db.execute("SELECT 1")


def test_unknown_run_cli_has_clear_error(ledger):
    path, _, _ = ledger
    result = CliRunner().invoke(app, ["repairs", "--database", str(path), "--run-id", "absent"])
    assert result.exit_code == 1 and "No saved research run" in result.output


def test_cli_json_matches_verified_inspection(ledger):
    path, _, rid = ledger
    result = CliRunner().invoke(
        app, ["repairs", "--database", str(path), "--run-id", rid, "--limit", "1"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == inspect_dataset_repairs(path, rid, limit=1)


def test_non_dataset_run_is_rejected(ledger):
    path, store, _ = ledger
    rid = store.create("Browser run", temporal.schema(True, True), TaskSpec(), None)
    with pytest.raises(VerboisyError, match="declared dataset"):
        inspect_dataset_repairs(path, rid)


def test_tampered_capture_cannot_produce_a_repair_report(ledger):
    path, store, rid = ledger
    store.db.execute("UPDATE dataset_assets SET metadata='{}' WHERE run_id=?", (rid,))
    store.db.commit()
    with pytest.raises(DatasetAssetError):
        inspect_dataset_repairs(path, rid)


def test_inspection_rejects_changed_accepted_values(ledger):
    path, store, rid = ledger
    row = store.db.execute(
        "SELECT id,payload FROM candidates WHERE run_id=? AND accepted=1 LIMIT 1", (rid,)
    ).fetchone()
    payload = json.loads(row["payload"])
    payload["record"]["population"] = 9999
    store.db.execute("UPDATE candidates SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
    store.db.commit()
    with pytest.raises(DatasetAssetError, match="captured source"):
        inspect_dataset_repairs(path, rid)
