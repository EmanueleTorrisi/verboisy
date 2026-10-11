# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Resume must validate its bounded rejected-evidence window before publishing offers."""

import json
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from verboisy.api import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import Candidate, Snapshot, Source, TaskSpec
from verboisy.extractor import range_changes as ranges
from verboisy.storage.changes import pending_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_extractor.test_range_changes import SCHEMA

DAMAGES = [
    "json",
    "scalar",
    "list",
    "shape",
    "extra",
    "scope_type",
    "duplicate_scope",
    "duplicate_quote",
    "escaped_key",
    "nan",
    "infinity",
    "overflow",
]


def state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ["research_runs", "events", "pages", "candidates", "snapshots", "records"]
    }


def create(store, *, interval=True):
    rid = store.create("Typical weights", SCHEMA, TaskSpec(identity_fields=["/name"]), None)
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    page = Snapshot(
        id=rid,
        url="https://example.test/",
        fetched_at="2026-01-01",
        content_hash="fixture",
        sources=[Source(id="e1", kind="text", scope="s1", text="Weight: 45 - 55 kg")],
        truncated=False,
    )
    store.queue(rid, page.url, 0, None)
    work = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()
    store.snapshot(rid, work["id"], page, "Weight: 45 - 55 kg")
    candidate = Candidate(
        scope="s1",
        record={"name": "Example", "weight": 50},
        evidence={
            "/weight": {
                "source": "e1",
                "quote": "45 - 55 kg" if interval else "50 kg",
                "transform": "number",
            }
        },
    )
    return rid, page, candidate


def insert(store, rid, page, payload, *, accepted=0):
    with store.db:
        store.db.execute(
            "INSERT INTO candidates(run_id,snapshot_id,payload,accepted) VALUES (?,?,?,?)",
            (rid, page.id if page is not None else None, payload, accepted),
        )


def damaged(candidate, damage):
    raw = candidate.model_dump_json()
    if damage in {"json", "scalar", "list", "shape"}:
        return {"json": "not JSON", "scalar": "42", "list": "[]", "shape": "{}"}[damage]
    if damage == "duplicate_scope":
        return raw.replace('"scope":', '"scope":"private contradictory value","scope":', 1)
    if damage == "duplicate_quote":
        return raw.replace('"quote":', '"quote":"private contradictory value","quote":', 1)
    if damage == "escaped_key":
        return raw.replace('"name":', '"\\u006eame":"private contradictory value","name":', 1)
    if damage in {"nan", "infinity", "overflow"}:
        return raw.replace(
            '"weight":50',
            '"weight":'
            + {
                "nan": "NaN",
                "infinity": "Infinity",
                "overflow": "1e999",
            }[damage],
        )
    value = candidate.model_dump()
    if damage == "extra":
        value["unknown"] = True
    else:
        value["scope"] = 123
    return json.dumps(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("placement", ["newest", "older"])
@pytest.mark.parametrize("operation", ["scan", "offer", "resume"])
async def test_corrupt_rejected_input_stops_before_offer_or_resume_work(
    tmp_path, monkeypatch, damage, placement, operation
):
    path = tmp_path / "resume.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store)
        payloads = [candidate.model_dump_json(), damaged(candidate, damage)]
        if placement == "older":
            payloads.reverse()
        for payload in payloads:
            insert(store, rid, page, payload)
        before = state(store)
    execution = AsyncMock(side_effect=AssertionError("Research must not start"))
    monkeypatch.setattr(ResearchRunner, "run", execution)
    with pytest.raises(
        VerboisyError, match="Stored rejected candidate failed integrity verification"
    ) as error:
        if operation == "resume":
            await arun(resume=rid, config=Settings(_env_file=None, sqlite_db_path=str(path)))
        else:
            with closing(ResearchStore(path, read_only=operation == "scan")) as store:
                if operation == "scan":
                    ranges.saved_range_evidence(store, rid)
                else:
                    ranges.offer_saved_range_change(store, rid)
    execution.assert_not_awaited()
    assert "private contradictory value" not in str(error.value)
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert state(reader) == before
        assert pending_change(reader, rid) is None


@pytest.mark.parametrize("included", [False, True])
def test_preflight_retains_exact_newest_first_hundred_candidate_limit(tmp_path, included):
    with closing(ResearchStore(tmp_path / "limit.db")) as store:
        rid, page, candidate = create(store, interval=False)
        insert(store, rid, page, "not JSON")
        for index in range(99 if included else 100):
            value = candidate.model_copy(update={"record": {"name": str(index), "weight": 50}})
            insert(store, rid, page, value.model_dump_json())
        before = state(store)
        if included:
            with pytest.raises(VerboisyError, match="Stored rejected candidate"):
                ranges.offer_saved_range_change(store, rid)
        else:
            evidence = ranges.saved_range_evidence(store, rid)
            assert len(evidence) == 100
            assert [item[1].candidates[0].record["name"] for item in evidence] == [
                str(index) for index in reversed(range(100))
            ]
            assert ranges.offer_saved_range_change(store, rid, saved_evidence=evidence) is None
        assert state(store) == before


@pytest.mark.parametrize("unavailable", ["null", "missing", "foreign", "accepted"])
def test_unavailable_or_unselected_evidence_does_not_enter_saved_scan(tmp_path, unavailable):
    with closing(ResearchStore(tmp_path / "scope.db")) as store:
        rid, page, _ = create(store, interval=False)
        other, foreign, _ = create(store)
        insert(store, other, foreign, "not JSON")
        if unavailable == "foreign":
            insert(store, rid, foreign, "not JSON")
        elif unavailable == "missing":
            # Exercise a legacy ledger written without foreign-key enforcement.
            store.db.execute("PRAGMA foreign_keys=OFF")
            try:
                insert(store, rid, page.model_copy(update={"id": "missing"}), "not JSON")
            finally:
                store.db.execute("PRAGMA foreign_keys=ON")
        else:
            insert(
                store,
                rid,
                None if unavailable == "null" else page,
                "not JSON",
                accepted=1 if unavailable == "accepted" else 0,
            )
        before = state(store)
        assert ranges.saved_range_evidence(store, rid) == []
        assert ranges.offer_saved_range_change(store, rid) is None
        assert state(store) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("interval", [False, True])
async def test_valid_resume_scans_once_and_preserves_presentation_and_budget(
    tmp_path, monkeypatch, legacy, interval
):
    path = tmp_path / "valid.db"
    with closing(ResearchStore(path)) as store:
        rid, page, candidate = create(store, interval=interval)
        insert(
            store, rid, page, json.dumps(candidate.model_dump(exclude_defaults=legacy), indent=2)
        )
    loads = []
    original = ResearchStore.load_snapshot

    def tracked(store, run_id, snapshot_id):
        loads.append((run_id, snapshot_id))
        return original(store, run_id, snapshot_id)

    monkeypatch.setattr(ResearchStore, "load_snapshot", tracked)
    executions = []

    async def offline(runner, steps):
        executions.append(runner.rid)
        runner.store.finish(rid, "PAUSED", "fixture", 17, 796)

    monkeypatch.setattr(ResearchRunner, "run", offline)
    result = await arun(resume=rid, config=Settings(_env_file=None, sqlite_db_path=str(path)))
    assert loads == [(rid, page.id)]
    assert executions == ([] if interval else [rid])
    assert result.stop_reason == ("proposed_changes" if interval else "fixture")
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert bool(pending_change(reader, rid)) == interval
        assert len(reader.events(rid, "presentation_preferences")) == 1
        assert (reader.load(rid)["tokens"], reader.load(rid)["reserved"]) == (17, 796)
