# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Generated metadata remains separate from source identities and saved evidence."""

import json
from unittest.mock import Mock

import pytest
from verboisy.api import arun
from verboisy.evidence.models import Candidate, TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.evidence.verify import verify
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


async def test_declared_id_is_rejected_before_store(tmp_path, monkeypatch):
    spy = Mock(side_effect=AssertionError("store opened"))
    monkeypatch.setattr("verboisy.api.ResearchStore", spy)
    with pytest.raises(VerboisyError, match="reserved"):
        await arun(
            goal="Synthetic",
            schema={"type": "object", "properties": {"id": {"type": "string"}}},
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "run.db")),
        )
    spy.assert_not_called()


def test_open_schema_candidate_and_atomic_admission(tmp_path):
    page = snapshot("<p>source-123</p>", "https://example.test/", 1000)
    candidate = Candidate(scope="page", record={"id": "source-123"}, evidence={})
    assert verify(candidate, page, {"type": "object"}, TaskSpec()) == ["reserved_output_id"]
    store = ResearchStore(tmp_path / "run.db")
    try:
        rid = store.create("Synthetic", {"type": "object"}, TaskSpec(), None)
        before = store.db.total_changes
        with pytest.raises(VerboisyError, match="source id"):
            store.accept(rid, page, candidate, [], TaskSpec())
        assert store.db.total_changes == before
        assert store.db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize("method", ["evidence", "accepted_candidate"])
def test_legacy_selected_source_id_keeps_raw_payload(tmp_path, method):
    from contextlib import closing

    from tests.test_storage.test_admission_transactions import SCHEMA, capture

    with closing(ResearchStore(tmp_path / "ledger.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("Synthetic", SCHEMA, task, None)
        page, candidate = capture(store, rid, 31)
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        payload = candidate.model_dump()
        payload["record"]["id"] = "legacy-source"
        with store.db:
            store.db.execute("UPDATE candidates SET payload=?", (json.dumps(payload),))
            store.db.execute("UPDATE records SET payload=?", (json.dumps(payload["record"]),))
        before = list(store.db.iterdump())
        with pytest.raises(VerboisyError, match="source-ID"):
            store.evidence(rid) if method == "evidence" else store.accepted_candidate(
                rid, candidate, task
            )
        assert list(store.db.iterdump()) == before
