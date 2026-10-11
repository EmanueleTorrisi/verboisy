# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Admission must reject damaged selected references before disposition writes."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, admission_state, capture


@pytest.mark.parametrize("preference", [None, "new"])
@pytest.mark.parametrize(
    "damage,message",
    [
        ("foreign_candidate", "Accepted candidate belongs to another run"),
        ("null_candidate", "Selected record has no candidate"),
        ("missing_candidate", "Selected record has no candidate"),
        ("rejected_candidate", "Stored accepted candidate failed integrity verification"),
        ("foreign_snapshot", "Accepted candidate has no snapshot in this run"),
        ("missing_snapshot", "Accepted candidate has no snapshot in this run"),
    ],
)
def test_admission_rejects_damaged_previous_reference_without_mutating_either_run(
    tmp_path, preference, damage, message
):
    with closing(ResearchStore(tmp_path / "admission.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("Customers", SCHEMA, task, None)
        other = store.create("Other customers", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        foreign_page, foreign_candidate = capture(store, other, 40)
        store.accept(rid, old_page, old_candidate, [], task)
        store.accept(other, foreign_page, foreign_candidate, [], task)
        old_id = store.db.execute(
            "SELECT candidate_id FROM records WHERE run_id=?", (rid,)
        ).fetchone()[0]
        foreign_id = store.db.execute(
            "SELECT candidate_id FROM records WHERE run_id=?", (other,)
        ).fetchone()[0]
        page, candidate = capture(store, rid, 32)
        if damage in {"foreign_candidate", "null_candidate", "missing_candidate"}:
            # A persisted damaged reference can exist in an imported or externally
            # edited ledger; restore FK enforcement before testing admission.
            store.db.execute("PRAGMA foreign_keys=OFF")
            reference = {
                "foreign_candidate": foreign_id,
                "null_candidate": None,
                "missing_candidate": 999999,
            }[damage]
            with store.db:
                store.db.execute(
                    "UPDATE records SET candidate_id=? WHERE run_id=?", (reference, rid)
                )
            store.db.execute("PRAGMA foreign_keys=ON")
        elif damage == "rejected_candidate":
            with store.db:
                store.db.execute("UPDATE candidates SET accepted=0 WHERE id=?", (old_id,))
        else:
            with store.db:
                store.db.execute(
                    "UPDATE candidates SET snapshot_id=? WHERE id=?",
                    (foreign_page.id if damage == "foreign_snapshot" else None, old_id),
                )
        before = admission_state(store)
        with pytest.raises(VerboisyError, match=message):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert not store.db.in_transaction
        assert admission_state(store) == before
