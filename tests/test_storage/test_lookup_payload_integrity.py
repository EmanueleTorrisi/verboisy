# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Comparison lookups must validate the entire saved chain without ledger writes."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("operation", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("identity_fields", [["/name"], ["/name", "/age"]])
@pytest.mark.parametrize(
    "damage",
    [
        "snapshot_json",
        "snapshot_shape",
        "snapshot_id",
        "record_json",
        "record_shape",
        "record_value",
        "record_missing",
        "record_type",
        "record_nonfinite",
    ],
)
def test_lookup_rejects_damaged_payloads_after_read_only_reopen(
    tmp_path, operation, identity_fields, damage
):
    path = tmp_path / "lookup.db"
    with closing(ResearchStore(path)) as writer:
        task = TaskSpec(identity_fields=identity_fields)
        rid = writer.create("People", SCHEMA, task, None)
        page, candidate = capture(writer, rid, 31)
        writer.accept(rid, page, candidate, [], task)
        with writer.db:
            if damage.startswith("snapshot"):
                payload = {
                    "snapshot_json": "not JSON",
                    "snapshot_shape": "[]",
                    "snapshot_id": page.model_copy(update={"id": "wrong"}).model_dump_json(),
                }[damage]
                writer.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (payload, page.id))
            else:
                payload = {
                    "record_json": "not JSON",
                    "record_shape": "[]",
                    "record_value": '{"name":"Alice","age":99}',
                    "record_missing": '{"name":"Alice"}',
                    "record_type": '{"name":"Alice","age":"31"}',
                    "record_nonfinite": '{"name":"Alice","age":NaN}',
                }[damage]
                writer.db.execute("UPDATE records SET payload=? WHERE run_id=?", (payload, rid))
        before = evidence_state(writer)
    with closing(ResearchStore(path, read_only=True)) as reader:
        message = (
            "Stored snapshot failed"
            if damage.startswith("snapshot")
            else "Selected record payload differs"
        )
        with pytest.raises(VerboisyError, match=message):
            getattr(reader, operation)(rid, candidate, task)
        assert evidence_state(reader) == before


@pytest.mark.parametrize("operation", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("identity_fields", [["/name"], ["/name", "/age"]])
@pytest.mark.parametrize("legacy", [False, True])
def test_valid_lookup_preserves_historical_payloads_and_stable_selection(
    tmp_path, operation, identity_fields, legacy
):
    path = tmp_path / "historical.db"
    with closing(ResearchStore(path)) as writer:
        task = TaskSpec(identity_fields=identity_fields)
        rid = writer.create("People", SCHEMA, task, None)
        page, candidate = capture(writer, rid, 31)
        writer.accept(rid, page, candidate, [], task)
        with writer.db:
            writer.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?",
                (json.dumps(candidate.model_dump(exclude_defaults=legacy), indent=2), rid),
            )
            writer.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?",
                (json.dumps(page.model_dump(exclude_defaults=legacy), indent=2), page.id),
            )
            writer.db.execute(
                "UPDATE records SET payload=? WHERE run_id=?",
                (json.dumps({"age": 31, "name": "Alice"}, indent=2), rid),
            )
        before = evidence_state(writer)
    with closing(ResearchStore(path, read_only=True)) as reader:
        result = getattr(reader, operation)(rid, candidate, task)
        assert result == (candidate if operation == "accepted_candidate" else (candidate, page.id))
        assert evidence_state(reader) == before
