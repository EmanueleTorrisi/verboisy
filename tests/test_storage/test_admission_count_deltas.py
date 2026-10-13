# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Incremental counts must agree with committed SQL state through conflict recovery."""

import sqlite3
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore

from tests.test_storage.test_admission_transactions import SCHEMA, capture


def test_counts_follow_inserts_duplicates_replacements_and_conflicts(tmp_path):
    with closing(ResearchStore(tmp_path / "run.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        count = 0
        for age, preference, expected in [
            (31, None, "accepted"),
            (31, None, "duplicate"),
            (32, "new", "accepted"),
            (31, "old", "rejected"),
            (33, None, "rejected"),
            (33, None, "rejected"),
        ]:
            page, candidate = capture(store, rid, age)
            delta = []
            assert (
                store.accept(
                    rid, page, candidate, [], task, preference=preference, record_delta=delta
                )
                == expected
            )
            count += delta[0]
            assert (
                count
                == store.db.execute(
                    "SELECT COUNT(*) FROM records WHERE run_id=?", (rid,)
                ).fetchone()[0]
            )
        assert count == 0


def test_failed_admission_never_reports_a_committed_delta(tmp_path):
    with closing(ResearchStore(tmp_path / "run.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.db.execute(
            "CREATE TRIGGER reject_row BEFORE INSERT ON records "
            "BEGIN SELECT RAISE(ABORT, 'row rejected'); END"
        )
        store.db.commit()
        delta = []
        with pytest.raises(sqlite3.IntegrityError):
            store.accept(rid, page, candidate, [], task, record_delta=delta)
        assert delta == [] and store.records(rid) == []
