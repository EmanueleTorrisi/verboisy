# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Admission must preserve damaged history instead of replacing or rejecting it."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("preference", [None, "old", "new"])
@pytest.mark.parametrize(
    "damage,message",
    [
        ("candidate_json", "Stored accepted candidate failed integrity verification"),
        ("candidate_schema", "Stored accepted candidate failed integrity verification"),
        ("candidate_nonfinite", "Stored accepted candidate failed integrity verification"),
        ("identity_changed", "Evidence candidate identity differs from selected record"),
        ("identity_missing", "Evidence candidate identity differs from selected record"),
        ("snapshot_json", "Stored snapshot failed integrity verification"),
        ("snapshot_schema", "Stored snapshot failed integrity verification"),
        ("snapshot_id", "Stored snapshot failed integrity verification"),
        ("record_json", "Selected record payload differs from accepted candidate"),
        ("record_shape", "Selected record payload differs from accepted candidate"),
        ("record_value", "Selected record payload differs from accepted candidate"),
        ("record_nonfinite", "Selected record payload differs from accepted candidate"),
    ],
)
def test_damaged_admission_payload_preserves_history_across_reopen(
    tmp_path, preference, damage, message
):
    path = tmp_path / "payload.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        page, candidate = capture(store, rid, 32)
        if damage.startswith("candidate"):
            value = "not JSON" if damage.endswith("json") else "{}"
            if damage.endswith("nonfinite"):
                damaged = old_candidate.model_dump()
                damaged["record"]["age"] = float("nan")
                value = json.dumps(damaged)
            store.db.execute("UPDATE candidates SET payload=? WHERE run_id=?", (value, rid))
        elif damage.startswith("identity"):
            value = old_candidate.model_dump()
            if damage.endswith("changed"):
                value["record"]["name"] = "Bob"
            else:
                del value["record"]["name"]
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?", (json.dumps(value), rid)
            )
        elif damage.startswith("snapshot"):
            value = {"snapshot_json": "not JSON", "snapshot_schema": "{}"}.get(
                damage, old_page.model_copy(update={"id": "wrong-id"}).model_dump_json()
            )
            store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (value, old_page.id))
        else:
            value = {
                "record_json": "not JSON",
                "record_shape": "[]",
                "record_value": '{"name":"Alice","age":99}',
                "record_nonfinite": '{"name":"Alice","age":NaN}',
            }[damage]
            store.db.execute("UPDATE records SET payload=? WHERE run_id=?", (value, rid))
        store.db.commit()
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match=message):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert not store.db.in_transaction
        assert evidence_state(store) == before
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert evidence_state(reader) == before


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("preference", [None, "new"])
def test_compound_identity_damage_cannot_be_replaced(tmp_path, missing, preference):
    with closing(ResearchStore(tmp_path / "compound.db")) as store:
        task = TaskSpec(identity_fields=["/name", "/age"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        value = candidate.model_dump()
        if missing:
            del value["record"]["age"]
        else:
            value["record"]["age"] = 99
        with store.db:
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?", (json.dumps(value), rid)
            )
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match="identity differs"):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert evidence_state(store) == before


@pytest.mark.parametrize("preference", [None, "new"])
def test_whole_record_identity_checks_selected_values(tmp_path, preference):
    with closing(ResearchStore(tmp_path / "whole.db")) as store:
        task = TaskSpec()
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        with store.db:
            store.db.execute(
                "UPDATE records SET payload=? WHERE run_id=?",
                ('{"name":"Alice","age":99}', rid),
            )
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match="Selected record payload differs"):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert evidence_state(store) == before


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "preference,expected", [(None, "rejected"), ("old", "rejected"), ("new", "accepted")]
)
def test_historical_payloads_retain_valid_admission_behavior(
    tmp_path, legacy, preference, expected
):
    with closing(ResearchStore(tmp_path / "legacy.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        stable_id = store.records(rid)[0]["id"]
        candidate_payload = old_candidate.model_dump(exclude_defaults=legacy)
        snapshot_payload = old_page.model_dump(exclude_defaults=legacy)
        with store.db:
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?",
                (json.dumps(candidate_payload, indent=2), rid),
            )
            store.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?",
                (json.dumps(snapshot_payload, indent=2), old_page.id),
            )
        page, candidate = capture(store, rid, 32)
        assert store.accept(rid, page, candidate, [], task, preference=preference) == expected
        if preference == "new":
            assert store.records(rid) == [{"id": stable_id, "name": "Alice", "age": 32}]
        elif preference == "old":
            assert store.records(rid) == [{"id": stable_id, "name": "Alice", "age": 31}]
        else:
            assert store.records(rid) == []


@pytest.mark.parametrize("identity_fields", [[], ["/name", "/age"]])
@pytest.mark.parametrize("preference,expected", [(None, "duplicate"), ("new", "accepted")])
def test_valid_compound_and_whole_record_identity_keep_stable_id(
    tmp_path, identity_fields, preference, expected
):
    with closing(ResearchStore(tmp_path / "valid.db")) as store:
        task = TaskSpec(identity_fields=identity_fields)
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        before = store.records(rid)
        assert store.accept(rid, page, candidate, [], task, preference=preference) == expected
        assert store.records(rid) == before
