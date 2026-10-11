# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Ledger and portable replay must retain acquisition endpoint and ownership checks."""

import hashlib
import json
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.asset_bundle import asset_bundle, load_portable_assets
from verboisy.storage.assets import DatasetAssetError, _identifier
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore

from tests.test_storage.test_dataset_assets import capture

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}
BODIES = [
    ("csv", b"name\nAlice\n"),
    ("json", b'[{"name":"Alice"}]'),
    ("jsonl", b'{"name":"Alice"}\n'),
]
DAMAGES = ["empty_chain", "start", "end", "original_url", "final_url"]


def saved_state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("research_runs", "dataset_assets", "dataset_blobs", "events")
    }


def corrupt_metadata(value, damage):
    if damage == "empty_chain":
        value["redirect_chain"] = []
    elif damage in {"start", "end"}:
        value["redirect_chain"][0 if damage == "start" else -1] = "https://wrong.test/"
    else:
        value[damage] = "https://wrong.test/"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def preserve_generation(destination):
    paths = [destination] + [
        destination.with_suffix(destination.suffix + suffix)
        for suffix in (".manifest.json", ".evidence.json", ".events.json", ".assets.json")
    ]
    for path in paths:
        path.write_bytes(b"prior generation")
    return paths


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("operation", ["load", "list", "bundle", "export", "custom_rows"])
def test_rehashed_ledger_metadata_does_not_bypass_redirect_contract(tmp_path, damage, operation):
    database = tmp_path / "replay.db"
    destination = tmp_path / "rows.json"
    files = preserve_generation(destination)
    with closing(ResearchStore(database)) as writer:
        task = TaskSpec()
        rid = writer.create("Capture", SCHEMA, task, None)
        asset_id = writer.save_dataset_asset(rid, capture())
        row = writer.db.execute(
            "SELECT metadata FROM dataset_assets WHERE id=?", (asset_id,)
        ).fetchone()
        encoded = corrupt_metadata(json.loads(row[0]), damage)
        changed_id = _identifier(rid, encoded)
        with writer.db:
            writer.db.execute(
                "UPDATE dataset_assets SET id=?,metadata=? WHERE id=?",
                (changed_id, encoded, asset_id),
            )
        before = saved_state(writer)
    with closing(ResearchStore(database, read_only=True)) as reader:
        with pytest.raises(DatasetAssetError, match="redirect metadata"):
            if operation == "load":
                reader.load_dataset_asset(rid, changed_id)
            elif operation == "list":
                reader.dataset_assets(rid)
            elif operation == "bundle":
                asset_bundle(reader, rid)
            else:
                export_dataset(
                    reader,
                    rid,
                    destination,
                    SCHEMA,
                    task,
                    rows=[{"id": 1, "name": "Alice"}] if operation == "custom_rows" else None,
                )
        assert saved_state(reader) == before
    assert all(path.read_bytes() == b"prior generation" for path in files)


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("fmt,body", BODIES)
def test_rechecksummed_portable_metadata_retains_redirect_contract(tmp_path, damage, fmt, body):
    with closing(ResearchStore(tmp_path / "portable.db")) as store:
        task = TaskSpec()
        rid = store.create("Capture", SCHEMA, task, None)
        store.save_dataset_asset(rid, capture(body, fmt))
        manifest_path = export_dataset(store, rid, tmp_path / "rows.json", SCHEMA, task)
    manifest = json.loads(manifest_path.read_text())
    sidecar = tmp_path / manifest["asset_bundle"]
    bundle = json.loads(sidecar.read_text())
    entry = bundle["assets"][0]
    encoded = corrupt_metadata(entry["metadata"], damage)
    entry["id"] = _identifier(rid, encoded)
    sidecar.write_text(json.dumps(bundle))
    manifest["files"][sidecar.name] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    original_files = (sidecar.read_bytes(), manifest_path.read_bytes())
    with (
        patch("httpx.AsyncClient", side_effect=AssertionError("network access")),
        pytest.raises(DatasetAssetError, match="redirect metadata"),
    ):
        load_portable_assets(manifest_path)
    assert (sidecar.read_bytes(), manifest_path.read_bytes()) == original_files


@pytest.mark.parametrize("fmt,body", BODIES)
def test_repeat_capture_rejects_foreign_acquisition_without_writes(tmp_path, fmt, body):
    with closing(ResearchStore(tmp_path / "ownership.db")) as store:
        task = TaskSpec()
        rid = store.create("First", SCHEMA, task, None)
        other = store.create("Other", SCHEMA, task, None)
        download = capture(body, fmt)
        asset_id = store.save_dataset_asset(rid, download)
        with store.db:
            store.db.execute("UPDATE dataset_assets SET run_id=? WHERE id=?", (other, asset_id))
        before = saved_state(store)
        with pytest.raises(
            DatasetAssetError, match="Existing dataset acquisition failed integrity"
        ):
            store.save_dataset_asset(rid, download)
        assert saved_state(store) == before
        assert not store.db.in_transaction


@pytest.mark.parametrize("fmt,body", BODIES)
@pytest.mark.parametrize("direct", [False, True])
def test_valid_acquisitions_replay_without_network_and_preserve_history(
    tmp_path, fmt, body, direct
):
    database = tmp_path / "valid.db"
    task = TaskSpec()
    download = capture(body, fmt)
    if direct:
        download = replace(
            download, final_url=download.original_url, redirect_chain=(download.original_url,)
        )
    with closing(ResearchStore(database)) as writer:
        rid = writer.create("Capture", SCHEMA, task, None)
        asset_id = writer.save_dataset_asset(rid, download)
        assert writer.save_dataset_asset(rid, download) == asset_id
        expected = writer.load_dataset_asset(rid, asset_id)
        before = saved_state(writer)
    with (
        patch("httpx.AsyncClient", side_effect=AssertionError("network access")),
        closing(ResearchStore(database, read_only=True)) as reader,
    ):
        assert reader.load_dataset_asset(rid, asset_id) == expected
        assert reader.dataset_assets(rid) == [expected]
        manifest = export_dataset(reader, rid, tmp_path / "rows.json", SCHEMA, task)
        assert load_portable_assets(manifest) == [expected]
        assert saved_state(reader) == before
