# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inventory is bounded, verifies captures, and preserves run state and accounting."""

import json

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import TaskSpec
from verboisy.storage.assets import DatasetAssetError
from verboisy.storage.inventory import inspect_dataset_assets
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_dataset_assets import capture


@pytest.fixture
def ledger(tmp_path):
    database = tmp_path / "run.db"
    store = ResearchStore(str(database))
    rid = store.create("People", {}, TaskSpec(), None)
    first = store.save_dataset_asset(rid, capture('[{"name":"Anaïs"}]'.encode(), "json"))
    second = store.save_dataset_asset(rid, capture(b"name\r\nAna\r\n", "csv"))
    empty = store.save_dataset_asset(rid, capture(b"[]", "json"))
    store.close()
    return database, rid, [first, second, empty]


@pytest.mark.parametrize(
    "limit,truncated,count", [(1, True, 1), (2, True, 2), (3, False, 3), (100, False, 3)]
)
def test_inventory_order_limits_and_exact_metadata(ledger, limit, truncated, count):
    database, rid, ids = ledger
    store = ResearchStore(str(database))
    before = (store.load(rid), store.summary(rid), store.events(rid))
    expected = store.load_dataset_asset(rid, ids[0])
    store.close()
    report = inspect_dataset_assets(database, rid, limit=limit)
    assert report["truncated"] == truncated and report["limit"] == limit
    assert [asset["asset_id"] for asset in report["assets"]] == ids[:count]
    first = report["assets"][0]
    assert first["sha256"] == expected.download.dataset.sha256
    assert first["row_count"] == 1 and first["byte_count"] == len(
        expected.download.dataset.original_bytes
    )
    assert first["original_url"] == expected.download.original_url
    assert first["final_url"] == expected.download.final_url
    assert first["parser_version"] == "1" and first["format"] == "json"
    assert first["acquired_at"] == expected.acquired_at
    if count == 3:
        assert report["assets"][2]["row_count"] == 0
    store = ResearchStore(str(database))
    try:
        assert (store.load(rid), store.summary(rid), store.events(rid)) == before
    finally:
        store.close()


def test_cli_json_inventory_matches_helper(ledger):
    database, rid, _ = ledger
    result = CliRunner().invoke(
        app, ["assets", "--database", str(database), "--run-id", rid, "--limit", "2"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == inspect_dataset_assets(database, rid, limit=2)


def test_empty_and_completed_runs_are_inspectable(tmp_path):
    database = tmp_path / "run.db"
    store = ResearchStore(str(database))
    rid = store.create("empty", {}, TaskSpec(), None)
    store.db.execute("UPDATE research_runs SET status='COMPLETED' WHERE id=?", (rid,))
    store.db.commit()
    store.close()
    report = inspect_dataset_assets(database, rid)
    assert report["run_status"] == "COMPLETED" and report["assets"] == []
    assert not report["truncated"]


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "1"])
def test_invalid_limits_reject_before_open(tmp_path, limit):
    with pytest.raises(VerboisyError, match="limit"):
        inspect_dataset_assets(tmp_path / "absent.db", "run", limit=limit)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["absent", "directory", "symlink"])
def test_existing_database_required(tmp_path, kind):
    database = tmp_path / "run.db"
    if kind == "directory":
        database.mkdir()
    if kind == "symlink":
        database.symlink_to(tmp_path / "absent")
    with pytest.raises(VerboisyError, match="existing"):
        inspect_dataset_assets(database, "run")


def test_corrupt_capture_fails_and_releases_lock(ledger):
    database, rid, _ = ledger
    store = ResearchStore(str(database))
    store.db.execute("UPDATE dataset_blobs SET content=?", (b"corrupt",))
    store.db.commit()
    store.close()
    with pytest.raises(DatasetAssetError):
        inspect_dataset_assets(database, rid)
    result = CliRunner().invoke(app, ["assets", "--database", str(database), "--run-id", rid])
    assert result.exit_code == 1
    assert "inventory_version" not in result.output
    store = ResearchStore(str(database))
    store.close()


def test_unknown_run_rejects_and_releases_lock(ledger):
    database, _, _ = ledger
    with pytest.raises(VerboisyError):
        inspect_dataset_assets(database, "unknown")
    store = ResearchStore(str(database))
    store.close()


def test_inventory_is_run_scoped(ledger):
    database, rid, ids = ledger
    store = ResearchStore(str(database))
    other = store.create("other", {}, TaskSpec(), None)
    store.save_dataset_asset(other, capture(b'[{"name":"other"}]', "json"))
    store.close()
    assert [row["asset_id"] for row in inspect_dataset_assets(database, rid)["assets"]] == ids


def test_inventory_id_can_be_used_for_cli_mapping_review(tmp_path, ledger):
    database, rid, ids = ledger
    runner = CliRunner()
    inventory = runner.invoke(app, ["assets", "--database", str(database), "--run-id", rid])
    assert inventory.exit_code == 0
    asset_id = json.loads(inventory.output)["assets"][0]["asset_id"]
    assert asset_id == ids[0]
    projection = tmp_path / "projection.json"
    projection.write_text('{"fields":[{"source":"/name","target":"/name"}]}')
    report = tmp_path / "review.json"
    plan = tmp_path / "approved.json"
    reviewed = runner.invoke(
        app,
        [
            "map",
            "--database",
            str(database),
            "--run-id",
            rid,
            "--asset-id",
            asset_id,
            "--projection",
            str(projection),
            "--output",
            str(report),
            "--plan",
            str(plan),
        ],
    )
    assert reviewed.exit_code == 0, reviewed.output
    assert json.loads(report.read_text())["decision"] == "approved"
    assert json.loads(report.read_text())["asset_id"] == asset_id
    assert json.loads(plan.read_text())["fields"][0]["source"] == "/name"


@pytest.mark.parametrize("kind", ["empty", "foreign", "old", "duplicate_version", "malformed"])
def test_inspection_never_initializes_or_migrates_database(tmp_path, kind):
    import sqlite3

    database = tmp_path / "inspect.db"
    if kind == "malformed":
        database.write_bytes(b"not SQLite")
    else:
        db = sqlite3.connect(database)
        if kind == "foreign":
            db.execute("CREATE TABLE private_data(value TEXT)")
        if kind in ("old", "duplicate_version"):
            db.execute("CREATE TABLE research_meta(version INTEGER)")
            db.execute("INSERT INTO research_meta VALUES (?)", (3 if kind == "old" else 4,))
            if kind == "duplicate_version":
                db.execute("INSERT INTO research_meta VALUES (4)")
        db.commit()
        db.close()
    before = database.read_bytes()
    with pytest.raises(VerboisyError):
        inspect_dataset_assets(database, "run")
    assert database.read_bytes() == before


def test_read_only_connection_can_inspect_while_store_lock_is_held(ledger):
    database, rid, ids = ledger
    store = ResearchStore(str(database))
    try:
        assert inspect_dataset_assets(database, rid)["assets"][0]["asset_id"] == ids[0]
    finally:
        store.close()


def test_read_only_open_failure_is_reported(tmp_path, ledger):
    import sqlite3
    from unittest.mock import patch

    database, rid, _ = ledger
    with (
        patch(
            "verboisy.storage.inventory.sqlite3.connect",
            side_effect=sqlite3.OperationalError("blocked"),
        ),
        pytest.raises(VerboisyError, match="open"),
    ):
        inspect_dataset_assets(database, rid)
