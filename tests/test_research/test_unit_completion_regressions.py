# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Completion and resume regressions using real SQLite; no live browser or model."""

import csv
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.storage.exporters import DataExporter
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


def prepare_pair(store, rid, task, second_unit="persons"):
    accept_observation(store, rid, task, "thousands of persons")
    accept_observation(store, rid, task, second_unit, revision="base", name="Beta", population=3000)
    return ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))


def test_completion_normalizes_before_deciding_target(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        runner = prepare_pair(store, rid, task)
        raw = store.evidence(rid)
        assert runner.target_met() is True
        assert [r["population"] for r in store.records(rid)] == [2000, 3000]
        assert len(store.events(rid, "unit_normalization")) == 1
        assert runner.target_met() is True
        assert len(store.events(rid, "unit_normalization")) == 1
        assert store.evidence(rid) == raw


@pytest.mark.asyncio
async def test_resumed_run_completes_without_fetching_another_page(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        prepare_pair(store, rid, task)
        raw = store.evidence(rid)
    store = ResearchStore(str(tmp_path / "replay.db"))
    try:
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        runner.browser = AsyncMock()
        runner.process = AsyncMock(side_effect=AssertionError("No page fetch is needed"))
        assert await runner.run(max_steps=1) == ("COMPLETED", "target_met")
        runner.process.assert_not_awaited()
        assert [r["population"] for r in store.records(rid)] == [2000, 3000]
        assert store.evidence(rid) == raw
    finally:
        store.close()


def test_manual_normalization_exports_and_reopens_without_changing_evidence(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        runner = prepare_pair(store, rid, task)
        raw = store.evidence(rid)
        assert runner.ensure_unit_normalizations() == 1
        rows = store.records(rid)
        DataExporter.export_json(rows, tmp_path / "rows.json")
        DataExporter.export_csv(rows, tmp_path / "rows.csv")
        assert json.loads((tmp_path / "rows.json").read_text()) == rows
        with (tmp_path / "rows.csv").open(newline="") as stream:
            assert [int(r["population"]) for r in csv.DictReader(stream)] == [2000, 3000]
        assert runner.target_met() is True
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        assert reopened.records(rid) == rows
        assert reopened.evidence(rid) == raw
    finally:
        reopened.close()


def test_incompatible_units_cannot_be_normalized_into_completion(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        runner = prepare_pair(store, rid, task, second_unit="kg")
        assert runner.ensure_unit_normalizations() == 0
        assert runner.target_met() is False
        assert runner.dataset_consistency_gaps() == ("/population:incompatible_units",)
        assert store.events(rid, "unit_normalization") == []
        assert [r["population"] for r in store.records(rid)] == [2, 3000]
