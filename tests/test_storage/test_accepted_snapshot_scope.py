# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Accepted comparison evidence requires an existing snapshot in the same run."""

from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("binding", ["foreign", "missing", "null", "owned"])
def test_selected_candidate_requires_owned_snapshot(tmp_path, method, binding):
    path = tmp_path / "snapshot-reference.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("Owner", SCHEMA, task, None)
        target = store.create("Target", SCHEMA, task, None)
        foreign_page, _ = capture(store, owner, 31)
        page, candidate = capture(store, target, 32)
        assert store.accept(target, page, candidate, [], task) == "accepted"
        if binding != "owned":
            snapshot_id = {"foreign": foreign_page.id, "missing": "missing", "null": None}[binding]
            # Simulate a copied or damaged legacy ledger. Foreign and null links
            # already satisfy SQLite's nullable, existence-only foreign key.
            if binding == "missing":
                store.db.execute("PRAGMA foreign_keys=OFF")
            store.db.execute(
                "UPDATE candidates SET snapshot_id=? WHERE run_id=?", (snapshot_id, target)
            )
            store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        lookup = getattr(store, method)
        if binding == "owned":
            expected = candidate if method == "accepted_candidate" else (candidate, page.id)
            assert lookup(target, candidate, task) == expected
        else:
            with pytest.raises(
                VerboisyError, match="Accepted candidate has no snapshot in this run"
            ):
                lookup(target, candidate, task)
        assert evidence_state(store) == before
