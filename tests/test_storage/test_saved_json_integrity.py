# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved evidence must not hide contradictory fields behind JSON's last key."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.json_payload import decode_saved_json
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state
from tests.test_storage.test_export_payload_integrity import export_or_read

DAMAGES = [
    "candidate_root",
    "candidate_record",
    "candidate_proof",
    "candidate_escaped",
    "snapshot_root",
    "snapshot_source",
    "snapshot_escaped",
    "record_duplicate",
    "record_escaped",
    "record_nonfinite",
    "record_overflow",
]
SNAPSHOT_DAMAGES = [value for value in DAMAGES if value.startswith("snapshot")]


def message(damage):
    if damage.startswith("candidate"):
        return "Stored accepted candidate failed integrity verification"
    if damage.startswith("snapshot"):
        return "Stored snapshot failed integrity verification"
    return "Selected record payload differs from accepted candidate"


def corrupt(store, rid, page, candidate, damage):
    if damage.startswith("candidate"):
        table, column, identity = "candidates", "run_id", rid
        raw = candidate.model_dump_json()
        if damage == "candidate_root":
            raw = raw.replace('"scope":', '"scope":"private contradictory value","scope":', 1)
        elif damage == "candidate_record":
            raw = raw.replace('"name":', '"name":"private contradictory value","name":', 1)
        elif damage == "candidate_proof":
            raw = raw.replace('"source":', '"source":"private contradictory value","source":', 1)
        else:
            raw = raw.replace('"name":', '"\\u006eame":"private contradictory value","name":', 1)
    elif damage.startswith("snapshot"):
        table, column, identity = "snapshots", "id", page.id
        raw = page.model_dump_json()
        if damage == "snapshot_root":
            raw = raw.replace('"id":', '"id":"private contradictory value","id":', 1)
        elif damage == "snapshot_source":
            raw = raw.replace(
                '"sources":[{', '"sources":[{"text":"private contradictory value",', 1
            )
        else:
            raw = raw.replace('"id":', '"\\u0069d":"private contradictory value","id":', 1)
    else:
        table, column, identity = "records", "run_id", rid
        raw = {
            "record_duplicate": '{"name":"Alice","age":999,"age":31}',
            "record_escaped": '{"name":"Alice","\\u0061ge":999,"age":31}',
            "record_nonfinite": '{"name":"Alice","age":NaN}',
            "record_overflow": '{"name":"Alice","age":1e999}',
        }[damage]
    # The first values intentionally disagree while the final values match the
    # selected candidate. Permissive decoding would silently discard the first.
    with store.db:
        store.db.execute(f"UPDATE {table} SET payload=? WHERE {column}=?", (raw, identity))


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize(
    "operation",
    [
        "accepted_candidate",
        "accepted_candidate_context",
        "records",
        "evidence",
        "proof",
        "dataset",
        "custom_rows",
    ],
)
def test_ambiguous_saved_payloads_stop_reads_and_preserve_export_generation(
    tmp_path, damage, operation
):
    path = tmp_path / "json.db"
    destination = tmp_path / "rows.json"
    artifacts = [
        destination,
        tmp_path / "rows.proof.txt",
        tmp_path / "rows.json.manifest.json",
        tmp_path / "rows.json.evidence.json",
    ]
    for artifact in artifacts:
        artifact.write_bytes(b"previous generation")
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        corrupt(store, rid, page, candidate, damage)
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        with pytest.raises(VerboisyError, match=message(damage)) as error:
            if operation.startswith("accepted_candidate"):
                getattr(reader, operation)(rid, candidate, task)
            elif operation == "records":
                reader.records(rid)
            else:
                export_or_read(reader, rid, destination, task, operation)
        assert "private contradictory value" not in str(error.value)
        assert evidence_state(reader) == before
    assert all(artifact.read_bytes() == b"previous generation" for artifact in artifacts)


@pytest.mark.parametrize("damage", SNAPSHOT_DAMAGES)
def test_direct_snapshot_replay_rejects_duplicate_fields(tmp_path, damage):
    with closing(ResearchStore(tmp_path / "snapshot.db")) as store:
        rid = store.create("People", SCHEMA, TaskSpec(), None)
        page, candidate = capture(store, rid, 31)
        corrupt(store, rid, page, candidate, damage)
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match=message(damage)):
            store.load_snapshot(rid, page.id)
        assert evidence_state(store) == before


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("preference", [None, "old", "new"])
def test_duplicate_historical_fields_stop_replacement_without_disposition(
    tmp_path, damage, preference
):
    with closing(ResearchStore(tmp_path / "previous.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        old_page, old_candidate = capture(store, rid, 31)
        store.accept(rid, old_page, old_candidate, [], task)
        page, candidate = capture(store, rid, 32)
        corrupt(store, rid, old_page, old_candidate, damage)
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match=message(damage)):
            store.accept(rid, page, candidate, [], task, preference=preference)
        assert evidence_state(store) == before


@pytest.mark.parametrize("damage", SNAPSHOT_DAMAGES)
@pytest.mark.parametrize("preference", [None, "old", "new"])
@pytest.mark.parametrize("reasons", [[], ["unsupported_value"]])
def test_incoming_duplicate_snapshot_stops_acceptance_and_rejection(
    tmp_path, damage, preference, reasons
):
    with closing(ResearchStore(tmp_path / "incoming.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        corrupt(store, rid, page, candidate, damage)
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match=message(damage)):
            store.accept(rid, page, candidate, reasons, task, preference=preference)
        assert evidence_state(store) == before


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":1,"x":2}',
        '{"nested":{"x":1,"x":1}}',
        '{"x":1,"\\u0078":1}',
        '[{"x":1,"x":2}]',
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        "-1e999",
    ],
)
def test_shared_decoder_rejects_ambiguity_and_nonfinite_numbers(raw):
    with pytest.raises(ValueError):
        decode_saved_json(raw)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("pretty", [False, True])
def test_valid_historical_evidence_retains_shape_order_and_values(tmp_path, legacy, pretty):
    with closing(ResearchStore(tmp_path / "valid.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        saved_candidate = candidate.model_dump(exclude_defaults=legacy)
        saved_snapshot = page.model_dump(exclude_defaults=legacy)
        with store.db:
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?",
                (json.dumps(saved_candidate, indent=2 if pretty else None), rid),
            )
            store.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?",
                (json.dumps(saved_snapshot, indent=2 if pretty else None), page.id),
            )
        before = evidence_state(store)
        assert store.load_snapshot(rid, page.id) == page
        assert store.accepted_candidate(rid, candidate, task) == candidate
        evidence = store.evidence(rid)[0]
        assert list(evidence["candidate"]) == list(saved_candidate)
        assert list(evidence["snapshot"]) == list(saved_snapshot)
        assert evidence["candidate"] == saved_candidate
        assert evidence["snapshot"] == saved_snapshot
        assert evidence_state(store) == before


@pytest.mark.parametrize(
    "value",
    [None, True, 123456789012345678901234567890, -0.0, "雪", [1, None], {"z": 1e308, "a": -1e-308}],
)
def test_shared_decoder_preserves_valid_json_values(value):
    assert decode_saved_json(json.dumps(value, ensure_ascii=False, allow_nan=False)) == value
