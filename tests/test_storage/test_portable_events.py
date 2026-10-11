# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Checksummed event history accompanies effective values and raw evidence."""

import csv
import hashlib
import json

import pytest
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore

from tests.test_storage.test_unit_replay_integrity import (
    SCHEMA,
    accept_observation,
    bound_event,
    ledger,
)


@pytest.mark.parametrize("extension", ["json", "csv"])
def test_normalization_event_is_portable_and_bound_to_raw_evidence(tmp_path, extension):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        transformation = bound_event(store, rid, record_id)
        store.event(rid, "unit_normalization", transformation)
        before = store.evidence(rid)
        destination = tmp_path / ("rows." + extension)
        manifest_path = export_dataset(store, rid, destination, SCHEMA, task)
        manifest = json.loads(manifest_path.read_text())
        assert manifest["format_version"] == 3
        assert set(manifest["files"]) == {
            destination.name,
            destination.name + ".evidence.json",
            destination.name + ".events.json",
        }
        for name, digest in manifest["files"].items():
            assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
        journal = json.loads((tmp_path / (destination.name + ".events.json")).read_text())
        assert journal["format_version"] == 1
        assert journal["run_id"] == rid
        assert journal["events"] == store.events(rid)
        normalized = [event for event in journal["events"] if event["kind"] == "unit_normalization"]
        assert normalized[0]["payload"] == transformation
        assert transformation["snapshot_id"] == before[0]["snapshot"]["id"]
        assert transformation["record_id"] == before[0]["record_id"]
        assert before[0]["candidate"]["record"]["population"] == 2
        if extension == "json":
            assert json.loads(destination.read_text())[0]["population"] == 2000
        else:
            with destination.open(newline="") as stream:
                row = next(csv.DictReader(stream))
            assert json.loads(row["population"]) == 2000
        assert json.loads((tmp_path / (destination.name + ".evidence.json")).read_text()) == before
        assert store.evidence(rid) == before
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        export_dataset(reopened, rid, destination, SCHEMA, task)
        assert json.loads((tmp_path / (destination.name + ".events.json")).read_text()) == journal
    finally:
        reopened.close()


def test_empty_export_has_a_checksummed_empty_journal(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        destination = tmp_path / "empty.json"
        manifest_path = export_dataset(store, rid, destination, SCHEMA, task)
        journal = destination.with_suffix(".json.events.json")
        assert json.loads(journal.read_text()) == {"format_version": 1, "run_id": rid, "events": []}
        manifest = json.loads(manifest_path.read_text())
        assert manifest["files"][journal.name] == hashlib.sha256(journal.read_bytes()).hexdigest()


def test_event_export_failure_leaves_no_committed_manifest(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        destination = tmp_path / "rows.json"
        manifest_path = export_dataset(store, rid, destination, SCHEMA, task)
        assert manifest_path.exists()
        monkeypatch.setattr(
            store,
            "events",
            lambda *_args: [{"kind": "fixture", "payload": float("nan"), "created_at": "saved"}],
        )
        with pytest.raises(ValueError):
            export_dataset(store, rid, destination, SCHEMA, task)
        assert not manifest_path.exists()
