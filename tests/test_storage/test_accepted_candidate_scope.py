# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A selected row cannot borrow an accepted candidate from another run."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("foreign", [False, True])
def test_accepted_candidate_lookup_checks_reference_run(tmp_path, method, foreign):
    path = tmp_path / "candidate.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("Owner", SCHEMA, task, None)
        target = store.create("Target", SCHEMA, task, None)
        owner_page, owner_candidate = capture(store, owner, 31)
        target_page, target_candidate = capture(store, target, 32)
        store.accept(owner, owner_page, owner_candidate, [], task)
        store.accept(target, target_page, target_candidate, [], task)
        if foreign:
            candidate_id = store.db.execute(
                "SELECT candidate_id FROM records WHERE run_id=?", (owner,)
            ).fetchone()[0]
            # SQLite permits this reference: the candidate exists, but ownership
            # is not encoded in the foreign key. Simulate a damaged legacy row.
            store.db.execute(
                "UPDATE records SET candidate_id=? WHERE run_id=?", (candidate_id, target)
            )
            store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        lookup = getattr(store, method)
        if foreign:
            with pytest.raises(VerboisyError, match="Accepted candidate belongs to another run"):
                lookup(target, target_candidate, task)
        else:
            result = lookup(target, target_candidate, task)
            expected = (
                target_candidate
                if method == "accepted_candidate"
                else (target_candidate, target_page.id)
            )
            assert result == expected
        assert evidence_state(store) == before
