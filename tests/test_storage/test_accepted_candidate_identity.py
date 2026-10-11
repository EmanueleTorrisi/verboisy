# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Selected comparison evidence must still describe the requested identity."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("damage", ["changed", "missing", "compound"])
def test_selected_candidate_identity_mismatch_is_read_only(tmp_path, method, damage):
    path = tmp_path / "identity.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name", "/age"] if damage == "compound" else ["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        changed = candidate.model_copy(deep=True)
        if damage == "changed":
            changed.record["name"] = "Bob"
        elif damage == "missing":
            del changed.record["name"]
        else:
            changed.record["age"] = 32
        store.db.execute(
            "UPDATE candidates SET payload=? WHERE run_id=?", (changed.model_dump_json(), rid)
        )
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(
            VerboisyError, match="Accepted candidate identity differs from selected record"
        ):
            getattr(store, method)(rid, candidate, task)
        assert evidence_state(store) == before


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
def test_same_identity_replacement_still_returns_current_candidate(tmp_path, method):
    path = tmp_path / "identity.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        stable_id = store.records(rid)[0]["id"]
        page, candidate = capture(store, rid, 32)
        assert store.accept(rid, page, candidate, [], task, preference="new") == "accepted"
        assert store.records(rid)[0]["id"] == stable_id
    with closing(ResearchStore(path, read_only=True)) as store:
        expected = candidate if method == "accepted_candidate" else (candidate, page.id)
        assert getattr(store, method)(rid, old_candidate, task) == expected
