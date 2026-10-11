# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Every evidence consumer must retain the captured page's run ownership."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state
from tests.test_storage.test_export_payload_integrity import export_or_read


def damage_page(store, rid, page, damage):
    other = store.create("Other", SCHEMA, TaskSpec(identity_fields=["/name"]), None)
    foreign, _ = capture(store, other, 40)
    foreign_pid = store.db.execute(
        "SELECT page_id FROM snapshots WHERE id=?", (foreign.id,)
    ).fetchone()[0]
    store.db.execute("PRAGMA foreign_keys=OFF")
    with store.db:
        store.db.execute("UPDATE pages SET url=? WHERE id=?", ("https://other.test/", foreign_pid))
        if damage == "owner":
            store.db.execute(
                "UPDATE pages SET run_id=? WHERE id=(SELECT page_id FROM snapshots WHERE id=?)",
                (other, page.id),
            )
        else:
            # A corrupt ledger may have been written by a connection without
            # foreign-key enforcement; LEFT JOIN must expose a missing page.
            store.db.execute(
                "UPDATE snapshots SET page_id=? WHERE id=?",
                (foreign_pid if damage == "foreign" else 999999, page.id),
            )

    store.db.execute("PRAGMA foreign_keys=ON")


@pytest.mark.parametrize("damage", ["foreign", "missing", "owner"])
@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize(
    "operation",
    [
        "load_snapshot",
        "accepted_candidate",
        "accepted_candidate_context",
        "records",
        "evidence",
        "proof",
        "dataset",
        "custom_rows",
    ],
)
def test_read_and_export_reject_foreign_or_missing_origin_after_reopen(
    tmp_path, damage, normalized, operation
):
    path = tmp_path / "origin.db"
    destination = tmp_path / "rows.json"
    artifacts = [
        destination,
        tmp_path / "rows.proof.txt",
        tmp_path / "rows.json.manifest.json",
        tmp_path / "rows.json.evidence.json",
    ]
    for artifact in artifacts:
        artifact.write_bytes(b"previous generation")
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        if normalized:
            store.event(rid, "unit_normalization", {})
        damage_page(store, rid, page, damage)
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        with pytest.raises(VerboisyError, match="Stored snapshot has no page in this run"):
            if operation == "load_snapshot":
                reader.load_snapshot(rid, page.id)
            elif operation.startswith("accepted_candidate"):
                getattr(reader, operation)(rid, candidate, task)
            elif operation == "records":
                reader.records(rid)
            else:
                export_or_read(reader, rid, destination, task, operation)
        assert evidence_state(reader) == before
    assert all(artifact.read_bytes() == b"previous generation" for artifact in artifacts)


@pytest.mark.parametrize("damage", ["foreign", "missing", "owner"])
@pytest.mark.parametrize("target", ["current", "previous"])
@pytest.mark.parametrize("preference", [None, "old", "new"])
@pytest.mark.parametrize("reasons", [[], ["unsupported_value"]])
def test_admission_rejects_damaged_origin_before_any_disposition(
    tmp_path, damage, target, preference, reasons
):
    with closing(ResearchStore(tmp_path / "admission.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        page, candidate = capture(store, rid, 32)
        damage_page(store, rid, page if target == "current" else old_page, damage)
        before = evidence_state(store)
        if target == "previous" and reasons and damage != "owner":
            # Rejected candidates use their whole-record key and do not consult
            # a previous selected identity. Only the current snapshot is used.
            # Moving their shared page damages both snapshots instead.
            store.accept(rid, page, candidate, reasons, task, preference=preference)
        else:
            with pytest.raises(VerboisyError, match="Stored snapshot has no page in this run"):
                store.accept(rid, page, candidate, reasons, task, preference=preference)
            assert evidence_state(store) == before


@pytest.mark.parametrize("status", ["queued", "done", "failed", "deferred"])
@pytest.mark.parametrize("legacy", [False, True])
def test_owned_page_status_and_historical_payload_do_not_change_replay(tmp_path, status, legacy):
    path = tmp_path / "valid.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        with store.db:
            store.db.execute("UPDATE pages SET status=? WHERE run_id=?", (status, rid))
            store.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?",
                (json.dumps(page.model_dump(exclude_defaults=legacy), indent=2), page.id),
            )
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert reader.load_snapshot(rid, page.id) == page
        assert reader.accepted_candidate(rid, candidate, task) == candidate
        assert reader.evidence(rid)[0]["candidate"]["record"] == candidate.record
        assert evidence_state(reader) == before
