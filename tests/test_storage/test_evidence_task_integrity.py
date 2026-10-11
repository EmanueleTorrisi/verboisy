# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Evidence exports reject invalid task settings even when saved JSON is valid."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_saved_requirements_json import ledger_state


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize(
    "invalid_settings",
    [
        {"target_records": 0},
        {"target_records": 100001},
        {"identity_fields": 42},
        {"unknown_task_option": True},
    ],
)
def test_evidence_rejects_invalid_saved_task_without_mutation(
    tmp_path, read_only, invalid_settings
):
    path = tmp_path / "evidence.sqlite3"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        assert len(store.evidence(rid)) == 1
        damaged = task.model_dump() | invalid_settings
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (json.dumps(damaged), rid)
        )
        store.db.commit()

    with closing(ResearchStore(path, read_only=read_only)) as store:
        before = ledger_state(store)
        transaction_before = store.db.in_transaction
        # JSON validation alone cannot protect the export contract: the task
        # must also satisfy its model before selected evidence is returned.
        with pytest.raises(VerboisyError, match="Saved task failed integrity verification"):
            store.evidence(rid)
        assert ledger_state(store) == before
        assert store.db.in_transaction == transaction_before
