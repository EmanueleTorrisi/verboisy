# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Extension metadata cannot overwrite authoritative portable manifest facts."""

import hashlib
import json

import pytest
from verboisy.storage.dataset import export_dataset

from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_all_authoritative_manifest_fields_resist_metadata_overrides(tmp_path, suffix):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        destination = tmp_path / f"rows{suffix}"
        path = export_dataset(store, rid, destination, SCHEMA, task)
        original = json.loads(path.read_text())
        evidence = store.evidence(rid)
        state = store.load(rid)
        # Cover every authoritative field, including future additions and ledger summary fields.
        forged = {key: "forged" for key in original}
        forged.update(files={}, truth_verified=True, global_completeness_claimed=True)
        path = export_dataset(store, rid, destination, SCHEMA, task, metadata=forged)
        current = json.loads(path.read_text())
        assert current == original
        assert current["run_id"] == rid
        assert current["truth_verified"] is False
        assert current["global_completeness_claimed"] is False
        assert current["files"] == {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in (
                destination,
                destination.with_suffix(suffix + ".evidence.json"),
                destination.with_suffix(suffix + ".events.json"),
            )
        }
        assert store.evidence(rid) == evidence
        assert store.load(rid) == state


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"string_mode": False, "grouping": None, "sort": [], "custom_note": "Fixture export"},
    ],
)
def test_extension_metadata_remains_available(tmp_path, metadata):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        path = export_dataset(store, rid, tmp_path / "rows.json", SCHEMA, task, metadata=metadata)
        manifest = json.loads(path.read_text())
        for key, value in (metadata or {}).items():
            assert manifest[key] == value
        assert all(cell["status"] == "resolved" for cell in manifest["cell_lineage"])
