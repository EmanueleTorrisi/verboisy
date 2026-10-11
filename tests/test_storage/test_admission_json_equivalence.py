# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""JSON presentation must not turn equal accepted values into identity conflicts."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore, encode

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state

FORMATS = ["pretty", "compact", "whitespace", "escaped", "reverse_keys"]


def historical_payload(record, style):
    if style == "pretty":
        return json.dumps(record, indent=4)
    if style == "compact":
        return json.dumps(record, separators=(",", ":"))
    if style == "whitespace":
        return "\n\t" + json.dumps(record) + "\n"
    if style == "escaped":
        return '{"\\u006eame":"\\u0041lice","age":31}'
    return json.dumps(dict(reversed(list(record.items()))))


def reformat_selected(store, rid, page, candidate, style):
    payload = historical_payload(candidate.record, style)
    with store.db:
        store.db.execute("UPDATE records SET payload=? WHERE run_id=?", (payload, rid))
        store.db.execute(
            "UPDATE candidates SET payload=? WHERE run_id=?",
            (json.dumps(candidate.model_dump(exclude_defaults=True), indent=2), rid),
        )
        store.db.execute(
            "UPDATE snapshots SET payload=? WHERE id=?",
            (json.dumps(page.model_dump(exclude_defaults=True), indent=2), page.id),
        )
    return payload


@pytest.mark.parametrize("style", FORMATS)
@pytest.mark.parametrize("identity_fields", [[], ["/name"], ["/name", "/age"]])
@pytest.mark.parametrize("preference", [None, "old", "new"])
def test_equal_values_retain_selection_and_do_not_create_conflicts(
    tmp_path, style, identity_fields, preference
):
    path = tmp_path / "equal.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=identity_fields)
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        payload = reformat_selected(store, rid, page, candidate, style)
        previous = dict(store.db.execute("SELECT * FROM records WHERE run_id=?", (rid,)).fetchone())
        snapshot_payload = store.db.execute(
            "SELECT payload FROM snapshots WHERE id=?", (page.id,)
        ).fetchone()[0]
        assert store.accept(rid, page, candidate, [], task, preference=preference) == (
            "accepted" if preference == "new" else "duplicate"
        )
        selected = dict(store.db.execute("SELECT * FROM records WHERE run_id=?", (rid,)).fetchone())
        assert selected["id"] == previous["id"]
        assert selected["stable_id"] == previous["stable_id"]
        assert selected["identity"] == previous["identity"]
        assert store.records(rid) == [{"id": previous["stable_id"], **candidate.record}]
        assert (
            store.db.execute("SELECT COUNT(*) FROM conflicts WHERE run_id=?", (rid,)).fetchone()[0]
            == 0
        )
        history = store.db.execute(
            "SELECT accepted,reasons FROM candidates WHERE run_id=? ORDER BY id", (rid,)
        ).fetchall()
        if preference == "new":
            assert selected["candidate_id"] != previous["candidate_id"]
            assert selected["payload"] == encode(candidate.record)
            assert [(row[0], json.loads(row[1])) for row in history] == [
                (0, ["superseded_candidate"]),
                (1, []),
            ]
            assert len(store.events(rid, "candidate_superseded")) == 1
        else:
            assert selected == previous
            assert selected["payload"] == payload
            assert [(row[0], json.loads(row[1])) for row in history] == [(1, []), (1, [])]
            assert store.events(rid, "candidate_superseded") == []
        assert (
            store.db.execute("SELECT payload FROM snapshots WHERE id=?", (page.id,)).fetchone()[0]
            == snapshot_payload
        )
        assert not store.db.in_transaction
        after = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert reader.records(rid) == [{"id": previous["stable_id"], **candidate.record}]
        assert evidence_state(reader) == after


@pytest.mark.parametrize("style", FORMATS)
@pytest.mark.parametrize("preference", [None, "old", "new"])
def test_genuine_value_changes_keep_conflict_and_preference_policy(tmp_path, style, preference):
    path = tmp_path / "changed.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        old_payload = reformat_selected(store, rid, old_page, old_candidate, style)
        stable_id = store.records(rid)[0]["id"]
        page, candidate = capture(store, rid, 32)
        result = store.accept(rid, page, candidate, [], task, preference=preference)
        assert result == ("accepted" if preference == "new" else "rejected")
        conflicts = store.db.execute(
            "SELECT COUNT(*) FROM conflicts WHERE run_id=?", (rid,)
        ).fetchone()[0]
        history = store.db.execute(
            "SELECT accepted,reasons FROM candidates WHERE run_id=? ORDER BY id", (rid,)
        ).fetchall()
        if preference is None:
            assert store.records(rid) == []
            assert conflicts == 1
            assert [(row[0], json.loads(row[1])) for row in history] == [
                (0, ["identity_conflict"]),
                (0, ["identity_conflict"]),
            ]
        elif preference == "old":
            assert conflicts == 0
            assert store.records(rid) == [{"id": stable_id, **old_candidate.record}]
            assert (
                store.db.execute("SELECT payload FROM records WHERE run_id=?", (rid,)).fetchone()[0]
                == old_payload
            )
            assert [(row[0], json.loads(row[1])) for row in history] == [
                (1, []),
                (0, ["superseded_candidate"]),
            ]
        else:
            assert conflicts == 0
            assert store.records(rid) == [{"id": stable_id, **candidate.record}]
            assert [(row[0], json.loads(row[1])) for row in history] == [
                (0, ["superseded_candidate"]),
                (1, []),
            ]
        assert not store.db.in_transaction
        after = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert evidence_state(reader) == after
