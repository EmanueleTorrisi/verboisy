# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Portable proof validates payload structure without rewriting historical JSON."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.proof import export_proof
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


def export_or_read(store, rid, destination, task, operation):
    if operation == "evidence":
        return store.evidence(rid)
    if operation == "proof":
        return export_proof(store, rid, destination)
    return export_dataset(
        store,
        rid,
        destination,
        SCHEMA,
        task,
        rows=[{"id": 1, "name": "Alice", "age": 31}] if operation == "custom_rows" else None,
    )


@pytest.mark.parametrize("operation", ["evidence", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize(
    "damage",
    ["candidate_json", "candidate_schema", "snapshot_json", "snapshot_schema", "snapshot_id"],
)
def test_export_payload_failure_preserves_existing_files(tmp_path, operation, damage):
    path = tmp_path / "payload.db"
    destination = tmp_path / "rows.json"
    artifacts = [destination, tmp_path / "rows.proof.txt", tmp_path / "rows.json.manifest.json"]
    for artifact in artifacts:
        artifact.write_bytes(b"existing generation")
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        if damage.startswith("candidate"):
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?",
                ("not JSON" if damage.endswith("json") else "{}", rid),
            )
        else:
            payload = {"snapshot_json": "not JSON", "snapshot_schema": "{}"}.get(
                damage, page.model_copy(update={"id": "another-snapshot"}).model_dump_json()
            )
            store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (payload, page.id))
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(VerboisyError, match="failed integrity verification"):
            export_or_read(store, rid, destination, task, operation)
        assert evidence_state(store) == before
        for artifact in artifacts:
            assert artifact.read_bytes() == b"existing generation"
        assert not (tmp_path / "rows.json.evidence.json").exists()


@pytest.mark.parametrize("operation", ["evidence", "proof", "dataset", "custom_rows"])
def test_export_preserves_valid_historical_payload_shape(tmp_path, operation):
    path = tmp_path / "payload.db"
    destination = tmp_path / "rows.json"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        candidate_payload = {key: value for key, value in candidate.model_dump().items() if value}
        snapshot_payload = {
            key: value for key, value in page.model_dump().items() if value is not None
        }
        store.db.execute(
            "UPDATE candidates SET payload=? WHERE run_id=?",
            (json.dumps(candidate_payload, sort_keys=True, indent=2), rid),
        )
        store.db.execute(
            "UPDATE snapshots SET payload=? WHERE id=?",
            (json.dumps(snapshot_payload, sort_keys=True, indent=2), page.id),
        )
        store.db.commit()
    with closing(ResearchStore(path, read_only=True)) as store:
        export_or_read(store, rid, destination, task, operation)
        evidence = store.evidence(rid)
        assert evidence[0]["candidate"] == candidate_payload
        assert evidence[0]["snapshot"] == snapshot_payload
        if operation in {"dataset", "custom_rows"}:
            assert json.loads((tmp_path / "rows.json.evidence.json").read_text()) == evidence
