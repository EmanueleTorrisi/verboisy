# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Preferred equal-value evidence refresh preserves identity and history."""

from contextlib import contextmanager

import pytest
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.storage.research import ResearchStore

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "population": {
            "type": "integer",
            "x-verboisy-temporal-class": "static",
            "x-verboisy-unit-sensitive": True,
            "x-verboisy-comparable-across-rows": True,
        },
        "revision": {"type": "string"},
    },
    "required": ["name", "population", "revision"],
    "additionalProperties": False,
}


@contextmanager
def ledger(tmp_path):
    store = ResearchStore(str(tmp_path / "replay.db"))
    try:
        task = TaskSpec(identity_fields=["/name"])
        rid = store.create("Population of Alba", SCHEMA, task, None)
        yield store, rid, task
    finally:
        store.close()


def accept_observation(
    store,
    rid,
    task,
    unit_label,
    revision="first",
    preference=None,
    *,
    name="Alba",
    population=2,
):
    record = {"name": name, "population": population, "revision": revision}
    sources = [
        Source(id=key, kind="text", text=str(value), scope="entity")
        for key, value in record.items()
    ]
    unit_quote = f"Population unit: {unit_label}."
    sources.append(Source(id="unit", kind="text", text=unit_quote, scope="entity"))
    page = Snapshot(
        id=f"snapshot-{revision}",
        url=f"https://example.test/{revision}",
        fetched_at="2026-10-03T00:00:00+00:00",
        content_hash=f"fixture-{revision}",
        sources=sources,
        truncated=False,
    )
    candidate = Candidate(
        scope="entity",
        record=record,
        evidence={
            f"/{key}": Proof(
                source=key,
                quote=str(value),
                transform="integer" if key == "population" else "text",
            )
            for key, value in record.items()
        },
    )
    assert verify(candidate, page, SCHEMA, task) == []
    store.queue(rid, page.url, 0, None)
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], page, "fixture")
    assert store.accept(rid, page, candidate, [], task, preference=preference) == "accepted"
    response = SourceAssessmentResponse.model_validate(
        {
            "assessments": [
                {
                    "pointer": "/population",
                    "unit": {
                        "label": unit_label,
                        "citation": {"source": "unit", "quote": unit_quote},
                    },
                }
            ]
        }
    )
    claims = ground_source_assessments(candidate, page, response)
    store.event(
        rid,
        "source_fitness",
        source_fitness_event(page, candidate, claims, cache_key="fixture", cache_hit=False),
    )
    store.mark_page(work["id"], "done")
    return store.evidence(rid)[0]["record_id"]


@pytest.mark.parametrize("preference", ["new", "old", None])
def test_equal_value_evidence_refresh_requires_explicit_preference(tmp_path, preference):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        before = store.evidence(rid)[0]
        records = store.records(rid)
        candidate = Candidate.model_validate(before["candidate"])
        newer = Snapshot.model_validate(before["snapshot"]).model_copy(
            update={"id": "refresh", "url": "https://example.test/refresh"}
        )
        store.queue(rid, newer.url, 0, None)
        work = store.next_page(rid)
        store.snapshot(rid, work["id"], newer, "fixture")
        outcome = store.accept(rid, newer, candidate, [], task, preference=preference)
        current = store.evidence(rid)[0]
        assert store.records(rid) == records
        assert current["record_id"] == before["record_id"]
        assert current["snapshot"]["id"] == (
            newer.id if preference == "new" else before["snapshot"]["id"]
        )
        assert outcome == ("accepted" if preference == "new" else "duplicate")
        events = store.events(rid, "candidate_superseded")
        assert len(events) == (1 if preference == "new" else 0)
        if preference == "new":
            event = events[0]["payload"]
            old = store.db.execute(
                "SELECT accepted,reasons,snapshot_id FROM candidates WHERE id=?",
                (event["previous_candidate_id"],),
            ).fetchone()
            assert old["accepted"] == 0
            assert "superseded_candidate" in old["reasons"]
            assert old["snapshot_id"] == before["snapshot"]["id"]
            assert (
                store.db.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE id=?", (old["snapshot_id"],)
                ).fetchone()[0]
                == 1
            )
        expected = store.evidence(rid)
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        assert reopened.evidence(rid) == expected
        assert reopened.records(rid) == records
    finally:
        reopened.close()
