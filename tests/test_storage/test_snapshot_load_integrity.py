# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Resume must distinguish absent evidence from invalid owned snapshot payloads."""

import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


@pytest.mark.parametrize("damage", ["json", "schema", "identity"])
def test_owned_snapshot_load_rejects_invalid_payload_without_writes(tmp_path, damage):
    path = tmp_path / "load.db"
    with closing(ResearchStore(path)) as store:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("People", SCHEMA, task, None)
        page, _ = capture(store, rid, 31)
        payload = {"json": "not JSON", "schema": "{}"}.get(
            damage, page.model_copy(update={"id": "another-snapshot"}).model_dump_json()
        )
        store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (payload, page.id))
        store.db.commit()
        before = evidence_state(store)
    with closing(ResearchStore(path, read_only=True)) as store:
        with pytest.raises(VerboisyError, match="Stored snapshot failed integrity verification"):
            store.load_snapshot(rid, page.id)
        assert evidence_state(store) == before


@pytest.mark.parametrize("missing", [False, True])
def test_snapshot_load_ignores_missing_or_foreign_corrupt_payload(tmp_path, missing):
    with closing(ResearchStore(tmp_path / "load.db")) as store:
        task = TaskSpec(identity_fields=["/name"])
        owner = store.create("Owner", SCHEMA, task, None)
        other = store.create("Other", SCHEMA, task, None)
        page, _ = capture(store, owner, 31)
        store.db.execute("UPDATE snapshots SET payload='not JSON' WHERE id=?", (page.id,))
        store.db.commit()
        before = evidence_state(store)
        assert store.load_snapshot(other, "missing" if missing else page.id) is None
        assert evidence_state(store) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_snapshot_load_preserves_historical_payload_compatibility(tmp_path, legacy):
    path = tmp_path / "load.db"
    with closing(ResearchStore(path)) as store:
        rid = store.create("People", SCHEMA, TaskSpec(identity_fields=["/name"]), None)
        page, _ = capture(store, rid, 31)
        payload = page.model_dump()
        if legacy:
            payload = {key: value for key, value in payload.items() if value is not None}
        store.db.execute(
            "UPDATE snapshots SET payload=? WHERE id=?",
            (json.dumps(payload, indent=2, sort_keys=True), page.id),
        )
        store.db.commit()
    with closing(ResearchStore(path, read_only=True)) as store:
        assert store.load_snapshot(rid, page.id) == page
