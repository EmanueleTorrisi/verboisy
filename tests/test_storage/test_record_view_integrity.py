# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Record views and exports must agree on the selected raw evidence values."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state
from tests.test_storage.test_export_payload_integrity import export_or_read


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("operation", ["records", "evidence", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize(
    "raw_payload",
    [
        "not JSON",
        "[]",
        '{"name":"Alice","age":99}',
        '{"name":"Alice"}',
        '{"name":"Alice","age":"31"}',
        '{"name":"Alice","age":NaN}',
    ],
)
def test_divergent_selected_values_fail_before_read_or_export(
    tmp_path, normalized, operation, raw_payload
):
    path = tmp_path / "views.db"
    destination = tmp_path / "rows.json"
    artifacts = [
        destination,
        tmp_path / "rows.proof.txt",
        tmp_path / "rows.json.manifest.json",
        tmp_path / "rows.json.evidence.json",
    ]
    for artifact in artifacts:
        artifact.write_bytes(b"existing generation")
    with closing(ResearchStore(path)) as writer:
        task = TaskSpec(identity_fields=["/name"])
        rid = writer.create("People", SCHEMA, task, None)
        page, candidate = capture(writer, rid, 31)
        writer.accept(rid, page, candidate, [], task)
        if normalized:
            # An ignored replay event still selects the normalized view path.
            writer.event(rid, "unit_normalization", {})
        with writer.db:
            writer.db.execute("UPDATE records SET payload=? WHERE run_id=?", (raw_payload, rid))
        before = evidence_state(writer)
    with closing(ResearchStore(path, read_only=True)) as reader:
        with pytest.raises(VerboisyError, match="Selected record payload differs"):
            if operation == "records":
                reader.records(rid)
            else:
                export_or_read(reader, rid, destination, task, operation)
        assert evidence_state(reader) == before
    assert all(artifact.read_bytes() == b"existing generation" for artifact in artifacts)


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize(
    "damage,message",
    [
        ("candidate_reference", "Selected record has no candidate"),
        ("candidate_payload", "Stored accepted candidate failed integrity verification"),
        ("identity", "Evidence candidate identity differs from selected record"),
        ("snapshot_payload", "Stored snapshot failed integrity verification"),
        ("snapshot_id", "Stored snapshot failed integrity verification"),
    ],
)
def test_record_view_modes_reject_the_same_damaged_evidence(tmp_path, normalized, damage, message):
    with closing(ResearchStore(tmp_path / "evidence.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        if normalized:
            store.event(rid, "unit_normalization", {})
        with store.db:
            if damage == "candidate_reference":
                store.db.execute("UPDATE records SET candidate_id=NULL WHERE run_id=?", (rid,))
            elif damage in {"candidate_payload", "identity"}:
                value = "not JSON"
                if damage == "identity":
                    changed = candidate.model_dump()
                    changed["record"]["name"] = "Bob"
                    value = json.dumps(changed)
                store.db.execute("UPDATE candidates SET payload=? WHERE run_id=?", (value, rid))
            else:
                value = (
                    "not JSON"
                    if damage == "snapshot_payload"
                    else page.model_copy(update={"id": "wrong-id"}).model_dump_json()
                )
                store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (value, page.id))
        before = evidence_state(store)
        with pytest.raises(VerboisyError, match=message):
            store.records(rid)
        assert evidence_state(store) == before


@pytest.mark.parametrize("identity_fields", [[], ["/name", "/age"]])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("normalized", [False, True])
def test_valid_historical_record_views_preserve_values_order_and_evidence_shape(
    tmp_path, identity_fields, legacy, normalized
):
    with closing(ResearchStore(tmp_path / "valid.db")) as store:
        task = TaskSpec(identity_fields=identity_fields)
        rid = store.create("People", SCHEMA, task, None)
        expected = []
        original_candidates = []
        for age in (31, 32):
            page, candidate = capture(store, rid, age)
            store.accept(rid, page, candidate, [], task)
            stable_id = store.db.execute(
                "SELECT stable_id FROM records WHERE run_id=? ORDER BY id DESC LIMIT 1", (rid,)
            ).fetchone()[0]
            expected.append({"id": stable_id, "name": "Alice", "age": age})
            candidate_value = candidate.model_dump(exclude_defaults=legacy)
            original_candidates.append(candidate_value)
            with store.db:
                store.db.execute(
                    "UPDATE records SET payload=? WHERE stable_id=?",
                    (json.dumps(candidate.record, indent=2), stable_id),
                )
                store.db.execute(
                    "UPDATE candidates SET payload=? WHERE run_id=? AND snapshot_id=?",
                    (json.dumps(candidate_value, indent=2), rid, page.id),
                )
                store.db.execute(
                    "UPDATE snapshots SET payload=? WHERE id=?",
                    (json.dumps(page.model_dump(exclude_defaults=legacy), indent=2), page.id),
                )
        if normalized:
            store.event(rid, "unit_normalization", {})
        before = evidence_state(store)
        assert store.records(rid) == expected
        assert [row["candidate"] for row in store.evidence(rid)] == original_candidates
        destination = tmp_path / "rows.json"
        export_or_read(store, rid, destination, task, "dataset")
        assert json.loads(destination.read_text()) == expected
        assert evidence_state(store) == before
