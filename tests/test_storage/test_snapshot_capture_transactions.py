# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved evidence is immutable through capture, including failed transactions."""

import sqlite3
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.storage.research import ResearchStore

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("variant", ["identical", "changed", "foreign_run"])
def test_duplicate_snapshot_cannot_overwrite_admitted_evidence(tmp_path, variant):
    path = tmp_path / "capture.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, owner, 31)
        assert store.accept(owner, page, candidate, [], task) == "accepted"
        target = owner
        if variant == "foreign_run":
            target = store.create("Other people", SCHEMA, task, None)
            store.queue(target, page.url, 0, None)
        pid = store.db.execute("SELECT id FROM pages WHERE run_id=?", (target,)).fetchone()[0]
        supplied = page.model_copy(deep=True)
        if variant != "identical":
            supplied.sources[0].text = "Changed capture"
        before = evidence_state(store)
        proof = store.evidence(owner)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            store.snapshot(target, pid, supplied, "replacement HTML")
        assert not store.db.in_transaction
        assert evidence_state(store) == before
        assert store.evidence(owner) == proof
    with closing(ResearchStore(path)) as reopened:
        assert evidence_state(reopened) == before
        assert reopened.evidence(owner) == proof


def test_snapshot_insert_fault_rolls_back_and_retry_survives_reopen(tmp_path):
    path = tmp_path / "capture.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        original, candidate = capture(store, rid, 31)
        store.accept(rid, original, candidate, [], task)
        html = "<article><h1>Bob</h1><p>42</p></article>"
        page = snapshot(html, "https://people.test/bob")
        store.queue(rid, page.url, 0, None)
        pid = store.db.execute("SELECT id FROM pages WHERE url=?", (page.url,)).fetchone()[0]
        before = evidence_state(store)
        store.db.execute(
            "CREATE TRIGGER fail_capture AFTER INSERT ON snapshots "
            "BEGIN SELECT RAISE(ABORT, 'capture fault'); END"
        )
        store.db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="capture fault"):
            store.snapshot(rid, pid, page, html)
        assert not store.db.in_transaction
        assert evidence_state(store) == before
    with closing(ResearchStore(path)) as reopened:
        assert evidence_state(reopened) == before
        assert reopened.load_snapshot(rid, page.id) is None
        reopened.db.execute("DROP TRIGGER fail_capture")
        reopened.db.commit()
        reopened.snapshot(rid, pid, page, html)
        assert reopened.load_snapshot(rid, page.id) == page
        assert reopened.load_snapshot(rid, original.id) == original
        assert reopened.records(rid)[0]["age"] == 31
    with closing(ResearchStore(path)) as reopened:
        assert reopened.load_snapshot(rid, page.id) == page
        assert reopened.load_snapshot(rid, original.id) == original
