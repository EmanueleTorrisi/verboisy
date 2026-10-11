# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Portable raw source bytes remain independently verifiable after database removal."""

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.api import _export_paths
from verboisy.evidence.models import TaskSpec
from verboisy.storage.asset_bundle import load_portable_assets
from verboisy.storage.assets import DatasetAssetError
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_research import test_dataset_ingestion as ingestion_fixtures
from tests.test_research.test_dataset_ingestion import schema, task
from tests.test_storage.test_dataset_assets import capture

dataset_site = ingestion_fixtures.site
no_paid_or_browser_work = ingestion_fixtures.no_paid_or_browser_work


@pytest.fixture
def exported(tmp_path):
    store = ResearchStore(str(tmp_path / "run.db"))
    spec = TaskSpec()
    target_schema = schema({"name": {"type": "string"}, "note": {"type": "string"}})
    rid = store.create("Capture", target_schema, spec, None)
    store.save_dataset_asset(rid, capture())
    manifest = export_dataset(store, rid, tmp_path / "rows.json", target_schema, spec)
    try:
        yield store, rid, manifest
    finally:
        store.close()


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b'\xef\xbb\xbfname,note\r\nAna\xc3\xafs,"first\nsecond"\r\n'),
        ("json", '[{"name":"李雷","note":null}]'.encode()),
        ("jsonl", b'\n{"name":"Ana","note":"=1+1"}\n\n'),
    ],
)
def test_original_bytes_and_locators_replay_without_database(tmp_path, fmt, body):
    database = tmp_path / "run.db"
    store = ResearchStore(str(database))
    spec = TaskSpec()
    target_schema = schema({"name": {"type": "string"}, "note": {"type": ["string", "null"]}})
    rid = store.create("Capture", target_schema, spec, None)
    first = capture(body, fmt)
    a = store.save_dataset_asset(rid, first)
    b = store.save_dataset_asset(rid, capture(b"name,note\nother,value\n"))
    saved = store.dataset_assets(rid)
    manifest = export_dataset(store, rid, tmp_path / "rows.json", target_schema, spec)
    store.close()
    database.unlink()
    info = json.loads(manifest.read_text(encoding="utf-8"))
    sidecar = tmp_path / info["asset_bundle"]
    assert info["asset_bundle"] == "rows.json.assets.json"
    assert info["files"][sidecar.name] == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    with patch("sqlite3.connect", side_effect=AssertionError("database access")):
        restored = load_portable_assets(manifest)
    assert restored == saved
    assert [item.id for item in restored] == [a, b]
    assert restored[0].download.dataset.original_bytes == body
    assert restored[0].download.remote_disposition == first.remote_disposition
    assert restored[0].download.dataset.rows == first.dataset.rows
    assert not (tmp_path.parent / "unsafe.csv").exists()


async def test_public_sorted_exports_bind_back_to_raw_rows(dataset_site, tmp_path):
    base, bodies, _, config = dataset_site
    bodies["/data"] = (200, '[{"name":"Beta","note":"=1+1"},{"name":"Anaïs","note":""}]'.encode())
    result = await arun(
        goal="Read rows",
        schema=schema({"name": {"type": "string"}, "note": {"type": "string"}}),
        task=task(base + "/data"),
        config=config,
        order=[("name", "asc")],
        export=[tmp_path / "rows.json", tmp_path / "rows.csv"],
    )
    assert result.completed and result.records[0]["name"] == "Anaïs"
    Path(config.sqlite_db_path).unlink()
    for manifest_path in result.manifest_paths:
        info = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert info["provenance"] == "exact_dataset_values"
        assert info["truth_verified"] is info["global_completeness_claimed"] is False
        restored = {item.id: item for item in load_portable_assets(manifest_path)}
        evidence_file = next(name for name in info["files"] if name.endswith(".evidence.json"))
        evidence = {
            item["record_id"]: item
            for item in json.loads((tmp_path / evidence_file).read_text(encoding="utf-8"))
        }
        for mapping in info["output_lineage"]:
            item = evidence[mapping["record_id"]]
            asset = restored[item["snapshot"]["dataset_asset_id"]]
            index = item["snapshot"]["dataset_row_index"]
            assert asset.download.dataset.rows[index - 1].values == item["candidate"]["record"]
        assert set(info["files"]) == {
            manifest_path.name.removesuffix(".manifest.json") + suffix
            for suffix in ("", ".evidence.json", ".events.json", ".assets.json")
        }
        for name, digest in info["files"].items():
            assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


def test_web_only_and_older_manifests_have_no_asset_sidecar(tmp_path):
    store = ResearchStore(str(tmp_path / "empty.db"))
    try:
        target_schema = schema({"name": {"type": "string"}})
        spec = TaskSpec()
        rid = store.create("No datasets", target_schema, spec, None)
        manifest = export_dataset(
            store,
            rid,
            tmp_path / "empty.json",
            target_schema,
            spec,
            metadata={"asset_bundle": "forged"},
        )
        info = json.loads(manifest.read_text(encoding="utf-8"))
        assert info["asset_bundle"] is None and load_portable_assets(manifest) == []
        assert not (tmp_path / "empty.json.assets.json").exists()
        del info["asset_bundle"]
        manifest.write_text(json.dumps(info), encoding="utf-8")
        assert load_portable_assets(manifest) == []
    finally:
        store.close()


def mutate(manifest, action):
    info = json.loads(manifest.read_text(encoding="utf-8"))
    sidecar = manifest.parent / info["asset_bundle"]
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    action(data)
    sidecar.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    info["files"][sidecar.name] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(info), encoding="utf-8")


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "run",
        "base64",
        "bytes",
        "metadata",
        "duplicate",
        "asset_list",
        "timestamp",
        "boolean_version",
    ],
)
def test_rechecks_internal_integrity_even_when_sidecar_hash_is_updated(exported, mutation):
    _, _, manifest = exported

    def change(value):
        if mutation == "version":
            value["format_version"] = 999
        elif mutation == "run":
            value["run_id"] = "other"
        elif mutation == "base64":
            value["assets"][0]["original_bytes_base64"] = "!"
        elif mutation == "bytes":
            value["assets"][0]["original_bytes_base64"] = base64.b64encode(
                b"name,note\nchanged,value\n"
            ).decode()
        elif mutation == "metadata":
            value["assets"][0]["metadata"]["dataset"]["rows"][0]["line_end"] = 999
        elif mutation == "asset_list":
            value["assets"] = {}
        elif mutation == "timestamp":
            value["assets"][0]["acquired_at"] = None
        elif mutation == "boolean_version":
            value["format_version"] = True
        else:
            value["assets"].append(value["assets"][0])

    mutate(manifest, change)
    with pytest.raises(DatasetAssetError):
        load_portable_assets(manifest)


def test_outer_checksum_is_verified(exported):
    _, _, manifest = exported
    info = json.loads(manifest.read_text(encoding="utf-8"))
    sidecar = manifest.parent / info["asset_bundle"]
    sidecar.write_bytes(sidecar.read_bytes() + b" ")
    with pytest.raises(DatasetAssetError, match="checksum mismatch"):
        load_portable_assets(manifest)


@pytest.mark.parametrize("name", ["../outside.json", "/outside.json", "", ".", "..", 123])
def test_manifest_cannot_choose_an_unsafe_sidecar_path(exported, name):
    _, _, manifest = exported
    info = json.loads(manifest.read_text(encoding="utf-8"))
    info["asset_bundle"] = name
    manifest.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(DatasetAssetError, match="Unsafe portable asset filename"):
        load_portable_assets(manifest)


def test_symlink_sidecar_is_rejected(exported, tmp_path):
    _, _, manifest = exported
    info = json.loads(manifest.read_text(encoding="utf-8"))
    sidecar = tmp_path / info["asset_bundle"]
    original = sidecar.read_bytes()
    other = tmp_path / "other.json"
    other.write_bytes(original)
    sidecar.unlink()
    sidecar.symlink_to(other)
    with pytest.raises(DatasetAssetError, match="Unsafe portable asset path"):
        load_portable_assets(manifest)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_reader_limits_are_rejected(exported, limit):
    with pytest.raises(ValueError, match="byte limit"):
        load_portable_assets(exported[2], max_bundle_bytes=limit)


def test_reader_byte_cap_and_missing_file_fail_closed(exported):
    _, _, manifest = exported
    with pytest.raises(DatasetAssetError, match="byte limit exceeded"):
        load_portable_assets(manifest, max_bundle_bytes=1)
    info = json.loads(manifest.read_text(encoding="utf-8"))
    (manifest.parent / info["asset_bundle"]).unlink()
    with pytest.raises(DatasetAssetError, match="Cannot verify"):
        load_portable_assets(manifest)


def test_corrupt_capture_does_not_replace_existing_export_manifest(exported):
    store, rid, manifest = exported
    before = manifest.read_bytes()
    store.db.execute("UPDATE dataset_blobs SET content=?", (b"bad",))
    store.db.commit()
    with pytest.raises(DatasetAssetError):
        export_dataset(
            store,
            rid,
            manifest.parent / "rows.json",
            schema({"name": {"type": "string"}}),
            TaskSpec(),
        )
    assert manifest.read_bytes() == before


def test_failed_sidecar_write_leaves_no_committed_generation(exported):
    store, rid, manifest = exported
    from verboisy.storage.dataset import _atomic_write

    def write(path, callback):
        if path.name.endswith(".assets.json"):
            raise OSError("injected failure")
        return _atomic_write(path, callback)

    with (
        patch("verboisy.storage.dataset._atomic_write", side_effect=write),
        pytest.raises(OSError, match="injected failure"),
    ):
        export_dataset(
            store,
            rid,
            manifest.parent / "rows.json",
            schema({"name": {"type": "string"}}),
            TaskSpec(),
        )
    assert not manifest.exists()


@pytest.mark.parametrize("suffix", [".assets.json", ".events.json"])
def test_output_sidecars_cannot_overwrite_database(tmp_path, suffix):
    destination = tmp_path / "rows.json"
    with pytest.raises(VerboisyError, match="database paths"):
        _export_paths(destination, str(destination) + suffix)
    with pytest.raises(VerboisyError, match="overlapping"):
        _export_paths([destination, Path(str(destination) + suffix)], str(tmp_path / "run.db"))


async def test_asset_sidecar_cannot_overwrite_schema_input(tmp_path):
    destination = tmp_path / "rows.json"
    source = tmp_path / "rows.json.assets.json"
    source.write_text(json.dumps(schema({"name": {"type": "string"}})), encoding="utf-8")
    with pytest.raises(VerboisyError, match="schema/task inputs"):
        await arun(goal="Read rows", schema=source, export=destination)


def test_invalid_manifest_shape_is_rejected(tmp_path):
    manifest = tmp_path / "invalid.json"
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(DatasetAssetError, match="Cannot verify"):
        load_portable_assets(manifest)
