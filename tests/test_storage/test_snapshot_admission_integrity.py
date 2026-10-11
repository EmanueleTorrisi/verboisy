# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Admission must reference the saved evidence, even when the snapshot ID is valid."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from .test_admission_transactions import SCHEMA, admission_state, capture


@pytest.mark.parametrize("reasons,preference", [([], None), (["invalid"], None), ([], "new")])
def test_changed_snapshot_cannot_write_admission(tmp_path, reasons, preference):
    with closing(ResearchStore(tmp_path / "ledger.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        if preference:
            store.accept(rid, page, candidate, [], task)
        changed = page.model_copy(deep=True)
        changed.sources[0].text = "Altered evidence"
        before = admission_state(store)
        with pytest.raises(VerboisyError, match="differs from its persisted evidence"):
            store.accept(rid, changed, candidate, reasons, task, preference=preference)
        assert admission_state(store) == before
        assert not store.db.in_transaction


@pytest.mark.parametrize("payload", ["not JSON", "{}"])
def test_corrupt_saved_snapshot_cannot_write_admission(tmp_path, payload):
    with closing(ResearchStore(tmp_path / "ledger.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (payload, page.id))
        store.db.commit()
        before = admission_state(store)
        with pytest.raises(VerboisyError, match="Stored snapshot failed integrity verification"):
            store.accept(rid, page, candidate, [], task)
        assert admission_state(store) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_equivalent_saved_snapshot_remains_compatible(tmp_path, legacy):
    with closing(ResearchStore(tmp_path / "ledger.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        payload = page.model_dump()
        if legacy:
            payload = {key: value for key, value in payload.items() if value is not None}
        store.db.execute(
            "UPDATE snapshots SET payload=? WHERE id=?",
            (json.dumps(payload, indent=2, sort_keys=True), page.id),
        )
        store.db.commit()
        assert store.accept(rid, page, candidate, [], task) == "accepted"
