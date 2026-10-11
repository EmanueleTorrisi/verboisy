# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exports must not omit orphaned selections or borrow another run's evidence."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.proof import export_proof
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("operation", ["evidence", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize(
    "damage",
    [
        "foreign_candidate",
        "foreign_snapshot",
        "null_candidate",
        "missing_candidate",
        "null_snapshot",
        "missing_snapshot",
        "rejected",
    ],
)
def test_export_rejects_damaged_evidence_references_before_writes(tmp_path, operation, damage):
    path = tmp_path / "export.db"
    destination = tmp_path / "rows.json"
    proof = tmp_path / "rows.proof.txt"
    manifest = tmp_path / "rows.json.manifest.json"
    for artifact in (destination, proof, manifest):
        artifact.write_bytes(b"existing generation")
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("Owner", SCHEMA, task, None)
        rid = store.create("Target", SCHEMA, task, None)
        foreign_page, foreign_candidate = capture(store, owner, 31)
        page, candidate = capture(store, rid, 32)
        store.accept(owner, foreign_page, foreign_candidate, [], task)
        store.accept(rid, page, candidate, [], task)
        foreign_id = store.db.execute(
            "SELECT candidate_id FROM records WHERE run_id=?", (owner,)
        ).fetchone()[0]
        if damage.startswith("missing"):
            store.db.execute("PRAGMA foreign_keys=OFF")
        if damage.endswith("candidate"):
            value = {
                "foreign_candidate": foreign_id,
                "null_candidate": None,
                "missing_candidate": 1000000,
            }[damage]
            store.db.execute("UPDATE records SET candidate_id=? WHERE run_id=?", (value, rid))
        elif damage == "rejected":
            store.db.execute("UPDATE candidates SET accepted=0 WHERE run_id=?", (rid,))
        else:
            value = {
                "foreign_snapshot": foreign_page.id,
                "null_snapshot": None,
                "missing_snapshot": "missing",
            }[damage]
            store.db.execute("UPDATE candidates SET snapshot_id=? WHERE run_id=?", (value, rid))
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(VerboisyError):
            if operation == "evidence":
                store.evidence(rid)
            elif operation == "proof":
                export_proof(store, rid, destination)
            else:
                export_dataset(
                    store,
                    rid,
                    destination,
                    SCHEMA,
                    task,
                    rows=[{"id": 1, "name": "Alice", "age": 32}]
                    if operation == "custom_rows"
                    else None,
                )
        assert evidence_state(store) == before
        for artifact in (destination, proof, manifest):
            assert artifact.read_bytes() == b"existing generation"
        assert not destination.with_suffix(".json.evidence.json").exists()
