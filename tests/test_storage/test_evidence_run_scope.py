# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Evidence writes cannot borrow another run's page or snapshot identifiers."""

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture


@pytest.fixture
def ledger(tmp_path):
    store = ResearchStore(tmp_path / "scope.sqlite3")
    try:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("Owner", SCHEMA, task, None)
        target = store.create("Target", SCHEMA, task, None)
        page, candidate = capture(store, owner, 32)
        yield store, owner, target, page, candidate, task
    finally:
        store.close()


def evidence_state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("snapshots", "candidates", "records", "conflicts", "events")
    }


@pytest.mark.parametrize("missing", [False, True])
def test_snapshot_capture_requires_page_in_requested_run(ledger, missing):
    store, owner, target, _, _, _ = ledger
    pid = store.db.execute("SELECT id FROM pages WHERE run_id=?", (owner,)).fetchone()[0]
    if missing:
        pid += 1000
    page = snapshot("<article>Target</article>", "https://target.test/")
    before = evidence_state(store)
    with pytest.raises(VerboisyError, match="Page does not belong to the requested run"):
        store.snapshot(target, pid, page, "<article>Target</article>")
    assert evidence_state(store) == before
    assert not store.db.in_transaction


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("rejected", [False, True])
def test_admission_requires_snapshot_in_requested_run(ledger, missing, rejected):
    store, _, target, page, candidate, task = ledger
    if missing:
        page = page.model_copy(update={"id": "missing-snapshot"})
    before = evidence_state(store)
    with pytest.raises(VerboisyError, match="Snapshot does not belong to the requested run"):
        store.accept(target, page, candidate, ["invalid_review"] if rejected else [], task)
    assert evidence_state(store) == before
    assert not store.db.in_transaction
    assert store.records(target) == []
    assert store.evidence(target) == []


def test_foreign_snapshot_cannot_replace_selected_target_record(ledger):
    store, _, target, foreign_page, candidate, task = ledger
    page, original = capture(store, target, 31)
    assert store.accept(target, page, original, [], task) == "accepted"
    before = evidence_state(store)
    records = store.records(target)
    with pytest.raises(VerboisyError, match="Snapshot does not belong to the requested run"):
        store.accept(target, foreign_page, candidate, [], task, preference="new")
    assert evidence_state(store) == before
    assert store.records(target) == records
    assert store.evidence(target)[0]["snapshot"]["id"] == page.id
