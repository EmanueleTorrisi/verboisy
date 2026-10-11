# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Completion and resume regressions using real SQLite; no live browser or model."""

from contextlib import contextmanager

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.evidence.verify import leaves, verify
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

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

SCHEMA["properties"]["population"] = {
    "type": "array",
    "items": SCHEMA["properties"]["population"],
}


@contextmanager
def ledger(tmp_path):
    store = ResearchStore(str(tmp_path / "replay.db"))
    try:
        task = TaskSpec(identity_fields=["/name"], target_records=2)
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
    record = {"name": name, "population": [population], "revision": revision}
    sources = [
        Source(id=key, kind="text", text=str(value), scope="entity")
        for key, value in leaves(record).items()
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
            key: Proof(
                source=key,
                quote=str(value),
                transform="integer" if key == "/population/0" else "text",
            )
            for key, value in leaves(record).items()
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
                    "pointer": "/population/0",
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


def pair(store, rid, task, second_unit="persons"):
    accept_observation(store, rid, task, "thousands of persons")
    accept_observation(store, rid, task, second_unit, revision="base", name="Beta", population=3000)
    return ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))


def test_array_scale_events_use_concrete_leaf_pointer(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        runner = pair(store, rid, task)
        raw = store.evidence(rid)
        assert runner.dataset_consistency_gaps() == ("/population/*:mixed_unit_scales",)
        assert runner.ensure_unit_normalizations() == 1
        assert store.events(rid, "unit_normalization")[0]["payload"]["pointer"] == "/population/0"
        assert [r["population"] for r in store.records(rid)] == [[2000], [3000]]
        assert runner.ensure_unit_normalizations() == 0
        assert runner.dataset_consistency_gaps() == ()
        assert store.evidence(rid) == raw


def test_array_scale_completion_survives_reopen(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        runner = pair(store, rid, task)
        assert runner.target_met() is True
        expected = store.records(rid)
        assert [r["population"] for r in expected] == [[2000], [3000]]
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        runner = ResearchRunner(reopened, rid, Settings(_env_file=None, search_provider="disabled"))
        assert runner.target_met() is True
        assert reopened.records(rid) == expected
        assert len(reopened.events(rid, "unit_normalization")) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("second_unit", ["kg", "thousands of persons"])
def test_array_controls_do_not_create_scale_events(tmp_path, second_unit):
    with ledger(tmp_path) as (store, rid, task):
        runner = pair(store, rid, task, second_unit)
        assert runner.ensure_unit_normalizations() == 0
        assert runner.target_met() is (second_unit == "thousands of persons")
        assert store.events(rid, "unit_normalization") == []
        assert [r["population"] for r in store.records(rid)] == [[2], [3000]]
