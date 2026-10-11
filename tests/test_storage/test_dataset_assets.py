# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Durable bytes and immutable row locations survive migration and resume."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.download import DownloadedDataset
from verboisy.storage.assets import DatasetAssetError, _identifier
from verboisy.storage.research import DB_VERSION, ResearchStore

from tests.test_storage.test_product_storage import _accepted_store


@pytest.fixture
def ledger(tmp_path):
    store = ResearchStore(str(tmp_path / "assets.db"))
    rid = store.create("dataset", {}, TaskSpec(), None)
    try:
        yield store, rid
    finally:
        store.close()


def capture(content=b'name,note\r\nAna\xc3\xafs,"first\nsecond"\r\n', fmt="csv"):
    return DownloadedDataset(
        "https://example.test/start",
        "https://example.test/data",
        ("https://example.test/start", "https://example.test/data"),
        "text/plain",
        'attachment; filename="../../unsafe.csv"',
        parse_dataset(content, fmt),
    )


@pytest.mark.parametrize(
    "content,fmt",
    [
        (b'\xef\xbb\xbfname,note\r\nAna\xc3\xafs,"first\nsecond"\r\n', "csv"),
        (
            '[{"name":"李雷","number":123456789012345678901234567890,"missing":null}]'.encode(),
            "json",
        ),
        (b'\n{"a":1}\n\n{"a":2}\n', "jsonl"),
        (b"[]", "json"),
    ],
)
def test_resume_preserves_bytes_metadata_types_and_locators(tmp_path, content, fmt):
    database = tmp_path / "resume.db"
    store = ResearchStore(str(database))
    rid = store.create("dataset", {}, TaskSpec(), None)
    download = capture(content, fmt)
    asset_id = store.save_dataset_asset(rid, download)
    original = store.load_dataset_asset(rid, asset_id)
    events = store.events(rid)
    assert original.download == download
    assert original.acquired_at
    assert store.records(rid) == []
    assert store.load(rid)["tokens"] == store.load(rid)["reserved"] == 0
    assert len(events) == 1
    assert events[0]["payload"]["sha256"] == hashlib.sha256(content).hexdigest()
    for row in original.download.dataset.rows:
        row.values.clear()
    store.close()
    with patch("httpx.AsyncClient", side_effect=AssertionError("network access")):
        reopened = ResearchStore(str(database))
        try:
            assert reopened.load_dataset_asset(rid, asset_id) == original
            assert reopened.dataset_assets(rid) == [original]
            assert reopened.save_dataset_asset(rid, download) == asset_id
            assert reopened.events(rid) == events
        finally:
            reopened.close()
    assert not (tmp_path / "unsafe.csv").exists()


def test_changed_bytes_and_metadata_preserve_history(ledger):
    store, rid = ledger
    first = capture()
    variants = [
        first,
        capture(b"name,note\nAna,changed\n"),
        replace(first, content_type="text/csv"),
    ]
    ids = [store.save_dataset_asset(rid, value) for value in variants]
    assert len(set(ids)) == 3
    assert [item.download for item in store.dataset_assets(rid)] == variants
    assert store.db.execute("SELECT count(*) FROM dataset_blobs").fetchone()[0] == 2
    assert len(store.events(rid, "dataset_asset")) == 3


def test_run_isolation_and_shared_bytes(ledger):
    store, rid = ledger
    other = store.create("other", {}, TaskSpec(), None)
    a = store.save_dataset_asset(rid, capture())
    b = store.save_dataset_asset(other, capture())
    assert a != b
    assert store.db.execute("SELECT count(*) FROM dataset_blobs").fetchone()[0] == 1
    assert [value.id for value in store.dataset_assets(rid)] == [a]
    assert [value.id for value in store.dataset_assets(other)] == [b]
    for run, asset in [(rid, b), (other, a), (rid, "missing")]:
        with pytest.raises(DatasetAssetError, match="requested run"):
            store.load_dataset_asset(run, asset)
    assert store.dataset_assets("missing") == []
    with pytest.raises(DatasetAssetError, match="No research run"):
        store.save_dataset_asset("missing", capture())


@pytest.mark.parametrize("change", ["hash", "row", "parser"])
def test_forged_parsed_dataset_is_rejected_before_writes(ledger, change):
    store, rid = ledger
    value = capture()
    parsed = value.dataset
    if change == "hash":
        parsed = replace(parsed, sha256="0" * 64)
    elif change == "row":
        parsed = replace(parsed, rows=(replace(parsed.rows[0], line_end=999),))
    else:
        parsed = replace(parsed, parser_version="future")
    with pytest.raises(DatasetAssetError, match="parsed rows differ"):
        store.save_dataset_asset(rid, replace(value, dataset=parsed))
    assert store.dataset_assets(rid) == []
    assert store.events(rid) == []


@pytest.mark.parametrize("chain", [(), ("wrong",), ("https://example.test/start", "wrong")])
def test_inconsistent_redirect_capture_is_rejected(ledger, chain):
    store, rid = ledger
    with pytest.raises(DatasetAssetError, match="redirect metadata"):
        store.save_dataset_asset(rid, replace(capture(), redirect_chain=chain))


def test_invalid_raw_asset_is_rejected(ledger):
    store, rid = ledger
    value = capture()
    with pytest.raises(DatasetAssetError, match="parser contract"):
        store.save_dataset_asset(
            rid, replace(value, dataset=replace(value.dataset, original_bytes=b""))
        )


@pytest.mark.parametrize(
    "column,value",
    [
        ("content", b"name,note\nAna,tampered\n"),
        ("content", b"not a dataset\nextra,cells\n"),
        ("metadata", '{"wrong":true}'),
        ("sha256", "0" * 64),
    ],
)
def test_corrupted_saved_acquisition_cannot_replay(ledger, column, value):
    store, rid = ledger
    asset_id = store.save_dataset_asset(rid, capture())
    if column == "content":
        store.db.execute("UPDATE dataset_blobs SET content=?", (value,))
    elif column == "metadata":
        store.db.execute("UPDATE dataset_assets SET metadata=?", (value,))
    else:
        store.db.execute(
            "INSERT INTO dataset_blobs VALUES(?,?)", (value, capture().dataset.original_bytes)
        )
        store.db.execute("UPDATE dataset_assets SET sha256=?", (value,))
    store.db.commit()
    with pytest.raises(DatasetAssetError):
        store.load_dataset_asset(rid, asset_id)


@pytest.mark.parametrize("mutation", ["bad_shape", "wrong_row", "bad_json"])
def test_rehashed_metadata_must_match_raw_bytes(ledger, mutation):
    store, rid = ledger
    store.save_dataset_asset(rid, capture())
    metadata = store.db.execute("SELECT metadata FROM dataset_assets").fetchone()[0]
    data = json.loads(metadata)
    if mutation == "bad_shape":
        data = {"dataset": {"format": "csv"}}
    elif mutation == "wrong_row":
        data["dataset"]["rows"][0]["line_start"] = 999
    metadata = (
        "{" if mutation == "bad_json" else json.dumps(data, ensure_ascii=False, sort_keys=True)
    )
    new_id = _identifier(rid, metadata)
    store.db.execute("UPDATE dataset_assets SET id=?,metadata=?", (new_id, metadata))
    store.db.commit()
    with pytest.raises(DatasetAssetError):
        store.load_dataset_asset(rid, new_id)


@pytest.mark.parametrize("corruption", ["blob", "metadata", "sha256", "missing_blob"])
def test_repeat_capture_does_not_hide_corruption(ledger, corruption):
    store, rid = ledger
    value = capture()
    asset_id = store.save_dataset_asset(rid, value)
    if corruption == "blob":
        store.db.execute("UPDATE dataset_blobs SET content=?", (b"tampered",))
    elif corruption == "metadata":
        store.db.execute("UPDATE dataset_assets SET metadata='{}'")
    elif corruption == "sha256":
        store.db.execute("INSERT INTO dataset_blobs VALUES(?,?)", ("wrong", b"other"))
        store.db.execute("UPDATE dataset_assets SET sha256='wrong'")
    else:
        store.db.commit()
        store.db.execute("PRAGMA foreign_keys=OFF")
        store.db.execute("DELETE FROM dataset_blobs")
    store.db.commit()
    with pytest.raises(DatasetAssetError, match="integrity verification"):
        store.save_dataset_asset(rid, value)
    assert store.db.execute("SELECT id FROM dataset_assets").fetchone()[0] == asset_id
    assert len(store.events(rid)) == 1


def test_failed_event_rolls_back_whole_capture(ledger):
    store, rid = ledger
    store.db.execute(
        "CREATE TRIGGER reject_asset_event BEFORE INSERT ON events "
        "BEGIN SELECT RAISE(ABORT,'injected failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.save_dataset_asset(rid, capture())
    assert store.dataset_assets(rid) == []
    assert store.db.execute("SELECT count(*) FROM dataset_blobs").fetchone()[0] == 0
    store.db.execute("DROP TRIGGER reject_asset_event")
    assert store.save_dataset_asset(rid, capture())


def test_version_three_migration_preserves_state(tmp_path):
    database = tmp_path / "migration.db"
    store, rid = _accepted_store(database)
    store.event(rid, "existing", {"value": "李雷"})
    store.finish(rid, "PAUSED", "max_steps", 17, 123)
    before, events = store.load(rid), store.events(rid)
    records, evidence, pages = store.records(rid), store.evidence(rid), store.pages(rid)
    store.db.executescript(
        "DROP TABLE dataset_assets; DROP TABLE dataset_blobs; UPDATE research_meta SET version=3;"
    )
    store.close()
    reopened = ResearchStore(str(database))
    try:
        assert (
            reopened.db.execute("SELECT version FROM research_meta").fetchone()[0]
            == DB_VERSION
            == 4
        )
        assert reopened.load(rid) == before
        assert reopened.events(rid) == events
        assert reopened.records(rid) == records
        assert reopened.evidence(rid) == evidence
        assert reopened.pages(rid) == pages
        assert reopened.dataset_assets(rid) == []
        assert reopened.save_dataset_asset(rid, capture())
    finally:
        reopened.close()
