# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""An orphaned selected record is damaged evidence, not an absent selection."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("binding", ["null", "missing", "absent_record", "valid"])
def test_lookup_distinguishes_missing_selection_from_missing_candidate(tmp_path, method, binding):
    path = tmp_path / "selected-reference.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        if binding == "absent_record":
            store.db.execute("DELETE FROM records WHERE run_id=?", (rid,))
        elif binding != "valid":
            # Existence-only nullable foreign keys permit null references.
            # Disable them solely to construct a missing-reference legacy fixture.
            if binding == "missing":
                store.db.execute("PRAGMA foreign_keys=OFF")
            store.db.execute(
                "UPDATE records SET candidate_id=? WHERE run_id=?",
                (None if binding == "null" else 1000000, rid),
            )
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        lookup = getattr(store, method)
        if binding in {"null", "missing"}:
            with pytest.raises(VerboisyError, match="Selected record has no candidate"):
                lookup(rid, candidate, task)
        elif binding == "absent_record":
            assert lookup(rid, candidate, task) is None
        else:
            expected = candidate if method == "accepted_candidate" else (candidate, page.id)
            assert lookup(rid, candidate, task) == expected
        assert evidence_state(store) == before
