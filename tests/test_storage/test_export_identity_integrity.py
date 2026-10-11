# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Portable proof must match the identity key selected during admission."""

from contextlib import closing
from types import SimpleNamespace

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.dataset_journal import _restore_row_journal, validate_dataset_evidence
from verboisy.storage.assets import DatasetAssetError
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state
from tests.test_storage.test_export_payload_integrity import export_or_read


@pytest.mark.parametrize("operation", ["evidence", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize("damage", ["changed", "missing", "compound", "whole_record", "task"])
def test_export_identity_failure_preserves_generation(tmp_path, operation, damage):
    path = tmp_path / "identity.db"
    destination = tmp_path / "rows.json"
    artifacts = [destination, tmp_path / "rows.proof.txt", tmp_path / "rows.json.manifest.json"]
    for artifact in artifacts:
        artifact.write_bytes(b"existing generation")
    fields = (
        [] if damage == "whole_record" else ["/name", "/age"] if damage == "compound" else ["/name"]
    )
    task = TaskSpec(identity_fields=fields)
    with closing(ResearchStore(path)) as store:
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        changed = candidate.model_copy(deep=True)
        if damage == "task":
            store.db.execute("UPDATE research_runs SET task_json='not JSON' WHERE id=?", (rid,))
        else:
            if damage == "changed":
                changed.record["name"] = "Bob"
            elif damage == "missing":
                del changed.record["name"]
            else:
                changed.record["age"] = 32
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?", (changed.model_dump_json(), rid)
            )
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        message = (
            "Saved task failed integrity verification"
            if damage == "task"
            else "Evidence candidate identity differs from selected record"
        )
        with pytest.raises(VerboisyError, match=message):
            export_or_read(store, rid, destination, task, operation)
        assert evidence_state(store) == before
        for artifact in artifacts:
            assert artifact.read_bytes() == b"existing generation"


@pytest.mark.parametrize("operation", ["evidence", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize("fields", [[], ["/name", "/age"]])
def test_export_identity_matches_admission_rules(tmp_path, operation, fields):
    task = TaskSpec(identity_fields=fields)
    with closing(ResearchStore(tmp_path / "identity.db")) as store:
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        export_or_read(store, rid, tmp_path / "rows.json", task, operation)
        assert store.evidence(rid)[0]["candidate"]["record"] == candidate.record


@pytest.mark.parametrize("active", [False, True])
def test_dataset_resume_retains_captured_source_error_category(tmp_path, active):
    path = tmp_path / "identity.db"
    task = TaskSpec(identity_fields=["/name"])
    with closing(ResearchStore(path)) as store:
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        changed = candidate.model_copy(deep=True)
        changed.record["name"] = "Bob"
        store.db.execute(
            "UPDATE candidates SET payload=? WHERE run_id=?", (changed.model_dump_json(), rid)
        )
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(DatasetAssetError, match="captured source") as failure:
            if active:
                _restore_row_journal(SimpleNamespace(store=store, rid=rid, task=task), [], set())
            else:
                validate_dataset_evidence(store, rid, task)
        assert isinstance(failure.value.__cause__, VerboisyError)
        assert "identity differs" in str(failure.value.__cause__)
        assert evidence_state(store) == before
