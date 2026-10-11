# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A rejected-evidence scan cannot leave a decision committed when replay fails."""

from asyncio import CancelledError
from contextlib import closing
from copy import deepcopy

import pytest
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.storage.changes import pending_change, propose_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_research.test_saved_range_resume_integrity import (
    DAMAGES,
    create,
    damaged,
    insert,
    state,
)


def proposal(store, rid):
    original = store.load(rid)
    import json

    schema = json.loads(original["schema_json"])
    schema = deepcopy(schema)
    record = schema.get("items", schema)
    field = record["properties"]["weight"]
    field["type"] = ["string", "null"]
    return propose_change(
        store,
        rid,
        {
            "description": "Use observed range strings",
            "goal": original["goal"],
            "schema": schema,
            "task": json.loads(original["task_json"]),
        },
    )


async def resume(path, rid, accept):
    return await arun(
        resume=False if accept else rid,
        okresume=rid if accept else False,
        config=Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled"),
    )


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("older", [False, True])
@pytest.mark.parametrize("accept", [False, True])
async def test_candidate_damage_preserves_real_pending_decision(tmp_path, damage, older, accept):
    path = tmp_path / "run.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store)
        change = proposal(store, rid)
        payloads = [candidate.model_dump_json(), damaged(candidate, damage)]
        if older:
            payloads.reverse()
        for raw in payloads:
            insert(store, rid, page, raw)
        before = state(store)
    with pytest.raises(VerboisyError, match="Stored rejected candidate failed integrity"):
        await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
        assert pending_change(store, rid) == change


@pytest.mark.parametrize("damage", ["json", "wrong_id", "missing_page", "foreign_page"])
@pytest.mark.parametrize("accept", [False, True])
async def test_snapshot_damage_preserves_real_pending_decision(tmp_path, damage, accept):
    import json

    path = tmp_path / "run.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store)
        proposal(store, rid)
        insert(store, rid, page, candidate.model_dump_json())
        if damage in {"json", "wrong_id"}:
            payload = (
                "not JSON" if damage == "json" else json.dumps({**page.model_dump(), "id": "other"})
            )
            store.db.execute("UPDATE snapshots SET payload=? WHERE id=?", (payload, page.id))
        else:
            other, foreign, _ = create(store)
            foreign_page = store.db.execute(
                "SELECT page_id FROM snapshots WHERE id=?", (foreign.id,)
            ).fetchone()[0]
            store.db.execute("PRAGMA foreign_keys=OFF")
            store.db.execute(
                "UPDATE snapshots SET page_id=? WHERE id=?",
                (999999 if damage == "missing_page" else foreign_page, page.id),
            )
        store.db.commit()
        before = state(store)
    with pytest.raises(VerboisyError):
        await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before


@pytest.mark.parametrize("fault", [OSError, RuntimeError, KeyboardInterrupt, CancelledError])
@pytest.mark.parametrize("accept", [False, True])
async def test_interrupted_preflight_preserves_decision_and_retries_once(
    tmp_path, monkeypatch, fault, accept
):
    path = tmp_path / "run.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store)
        proposal(store, rid)
        insert(store, rid, page, candidate.model_dump_json())
        before = state(store)
    original = ResearchStore.load_snapshot

    def fail(*args):
        raise fault("scan interrupted")

    monkeypatch.setattr(ResearchStore, "load_snapshot", fail)
    with pytest.raises(fault, match="scan interrupted"):
        await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert state(store) == before
    monkeypatch.setattr(ResearchStore, "load_snapshot", original)

    async def offline(runner, steps):
        runner.store.finish(rid, "PAUSED", "fixture", 17, 796)

    monkeypatch.setattr(ResearchRunner, "run", offline)
    await resume(path, rid, accept)
    with closing(ResearchStore(path, read_only=True)) as store:
        assert pending_change(store, rid) is None
        assert len(store.events(rid, "change_decided")) == 1
        assert (store.load(rid)["tokens"], store.load(rid)["reserved"]) == (17, 796)


@pytest.mark.parametrize("accept", [False, True])
async def test_valid_scan_precedes_decision_and_is_reused(tmp_path, monkeypatch, accept):
    path = tmp_path / "run.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store)
        proposal(store, rid)
        insert(store, rid, page, candidate.model_dump_json())
    original = ResearchStore.load_snapshot
    observed = []

    def tracked(store, run_id, snapshot_id):
        observed.append(len(store.events(run_id, "change_decided")))
        return original(store, run_id, snapshot_id)

    monkeypatch.setattr(ResearchStore, "load_snapshot", tracked)

    async def offline(runner, steps):
        runner.store.finish(rid, "PAUSED", "fixture", 17, 796)

    monkeypatch.setattr(ResearchRunner, "run", offline)
    await resume(path, rid, accept)
    assert observed == [0]
