# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real SQL faults must roll back admission before a reopened ledger can observe it."""

import sqlite3

import pytest
from verboisy.evidence.models import Candidate, Proof, TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.storage.research import ResearchStore

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
    "additionalProperties": False,
}


def capture(store, rid, age):
    html = f"<article><h1>Alice</h1><p>{age}</p></article>"
    page = snapshot(html, "https://people.test/")
    store.queue(rid, page.url, 0, None)
    work = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()
    store.snapshot(rid, work["id"], page, html)
    name = next(source for source in page.sources if source.text == "Alice")
    value = next(source for source in page.sources if source.text == str(age))
    candidate = Candidate(
        scope=name.scope,
        record={"name": "Alice", "age": age},
        evidence={
            "/name": Proof(source=name.id, quote="Alice"),
            "/age": Proof(source=value.id, quote=str(age), transform="number"),
        },
    )
    return page, candidate


def admission_state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("candidates", "records", "conflicts", "events")
    }


@pytest.mark.parametrize(
    "stage,trigger,preference",
    [
        ("insert", "BEFORE INSERT ON records", None),
        ("conflict", "BEFORE INSERT ON candidates", None),
        ("replacement_disposition", "BEFORE UPDATE ON candidates", "new"),
        ("replacement_record", "BEFORE UPDATE ON records", "new"),
        (
            "replacement_journal",
            "BEFORE INSERT ON events WHEN NEW.kind='candidate_superseded'",
            "new",
        ),
    ],
)
def test_admission_fault_rolls_back_across_reopen_and_retry(tmp_path, stage, trigger, preference):
    path = tmp_path / "admission.sqlite3"
    store = ResearchStore(path)
    try:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("Customers", SCHEMA, task, None)
        if stage != "insert":
            old_page, old_candidate = capture(store, rid, 31)
            assert store.accept(rid, old_page, old_candidate, [], task) == "accepted"
        page, candidate = capture(store, rid, 32)
        before = admission_state(store)
        previous_id = store.records(rid)[0]["id"] if stage != "insert" else None
        store.db.execute(
            f"CREATE TRIGGER fail_admission {trigger} "
            "BEGIN SELECT RAISE(ABORT, 'admission fault'); END"
        )
        store.db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="admission fault"):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert not store.db.in_transaction
        assert admission_state(store) == before
        store.close()
        store = ResearchStore(path)
        assert admission_state(store) == before
        store.db.execute("DROP TRIGGER fail_admission")
        store.db.commit()
        outcome = store.accept(rid, page, candidate, [], task, preference=preference)
        if stage == "conflict":
            assert outcome == "rejected"
            assert store.records(rid) == []
            assert store.db.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 1
            assert store.db.execute("SELECT SUM(accepted) FROM candidates").fetchone()[0] == 0
        else:
            assert outcome == "accepted"
            records = store.records(rid)
            assert len(records) == 1
            assert records[0]["age"] == 32
            if previous_id is not None:
                assert records[0]["id"] == previous_id
                assert len(store.events(rid, "candidate_superseded")) == 1
            assert store.db.execute("SELECT SUM(accepted) FROM candidates").fetchone()[0] == 1
    finally:
        store.close()
