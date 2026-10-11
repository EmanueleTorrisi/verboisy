# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Selected candidates must retain an accepted disposition and valid payload."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
@pytest.mark.parametrize("damage", ["rejected", "unknown", "json", "schema"])
def test_selected_candidate_integrity_failure_is_read_only(tmp_path, method, damage):
    path = tmp_path / "candidate.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        if damage in {"rejected", "unknown"}:
            store.db.execute(
                "UPDATE candidates SET accepted=? WHERE run_id=?",
                (0 if damage == "rejected" else None, rid),
            )
        else:
            store.db.execute(
                "UPDATE candidates SET payload=? WHERE run_id=?",
                ("not JSON" if damage == "json" else "{}", rid),
            )
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(
            VerboisyError, match="Stored accepted candidate failed integrity verification"
        ):
            getattr(store, method)(rid, candidate, task)
        assert evidence_state(store) == before


@pytest.mark.parametrize("method", ["accepted_candidate", "accepted_candidate_context"])
def test_selected_candidate_historical_defaults_remain_compatible(tmp_path, method):
    path = tmp_path / "candidate.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        store.accept(rid, page, candidate, [], task)
        payload = candidate.model_dump()
        # Older payloads may omit empty optional metadata. Let the model restore
        # defaults, rather than requiring identical serialized JSON.
        for key in (
            "temporal_evidence",
            "unit_evidence",
            "definition_evidence",
            "methodology_evidence",
        ):
            if key in payload and not payload[key]:
                del payload[key]
        store.db.execute(
            "UPDATE candidates SET payload=? WHERE run_id=?",
            (json.dumps(payload, sort_keys=True, indent=2), rid),
        )
        store.db.commit()
    with closing(ResearchStore(path, read_only=True)) as store:
        expected = candidate if method == "accepted_candidate" else (candidate, page.id)
        assert getattr(store, method)(rid, candidate, task) == expected
