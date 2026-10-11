# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Normalization integrity across real SQLite evidence and record views."""

from contextlib import contextmanager

import pytest
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_candidate_key,
    source_fitness_event,
)
from verboisy.core.units import canonical_unit, unit_normalization_event
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


def persist_scale(store, rid, record_id, label="thousands of persons", original=2):
    unit = canonical_unit(label)
    assert unit is not None
    payload = unit_normalization_event(
        record_id=record_id,
        pointer="/population",
        original_value=original,
        unit=unit,
    )
    assert payload is not None
    store.event(rid, "unit_normalization", payload)


def test_event_unit_must_match_accepted_source(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "persons")
        persist_scale(store, rid, record_id)

        assert store.records(rid)[0]["population"] == 2


def test_projection_cannot_chain_events_on_derived_values(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        persist_scale(store, rid, record_id)
        persist_scale(store, rid, record_id, original=2000)

        assert store.records(rid)[0]["population"] == 2000
        assert store.evidence(rid)[0]["candidate"]["record"]["population"] == 2


def test_superseded_candidate_does_not_transfer_its_unit(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        persist_scale(store, rid, record_id)
        replacement_id = accept_observation(
            store, rid, task, "persons", revision="second", preference="new"
        )

        assert replacement_id == record_id
        assert store.records(rid)[0]["population"] == 2
        assert store.evidence(rid)[0]["snapshot"]["id"] == "snapshot-second"


@pytest.mark.parametrize("forged_first", [True, False])
def test_wrong_scale_cannot_override_grounded_scale(tmp_path, forged_first):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        labels = ["million persons", "thousands of persons"]
        if not forged_first:
            labels.reverse()
        for label in labels:
            persist_scale(store, rid, record_id, label=label)

        assert store.records(rid)[0]["population"] == 2000


def test_grounded_legacy_event_is_idempotent_after_reopen(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        before = store.evidence(rid)
        persist_scale(store, rid, record_id)
        persist_scale(store, rid, record_id)
        expected = store.records(rid)
        assert expected[0]["population"] == 2000
        assert store.evidence(rid) == before

    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        assert reopened.records(rid) == expected
        assert reopened.records(rid) == expected
        assert reopened.evidence(rid) == before
    finally:
        reopened.close()


def test_tampered_result_is_not_projected(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        unit = canonical_unit("thousands of persons")
        payload = unit_normalization_event(
            record_id=record_id, pointer="/population", original_value=2, unit=unit
        )
        payload["normalized_value"] = 9999
        store.event(rid, "unit_normalization", payload)

        assert store.records(rid)[0]["population"] == 2


def bound_event(store, rid, record_id):
    row = store.evidence(rid)[0]
    candidate = Candidate.model_validate(row["candidate"])
    return unit_normalization_event(
        record_id=record_id,
        pointer="/population",
        original_value=2,
        unit=canonical_unit("thousands of persons"),
        candidate_key=source_fitness_candidate_key(candidate),
        snapshot_id=row["snapshot"]["id"],
    )


def test_bound_event_replays_identically_in_runner_and_store(tmp_path):
    from verboisy.core.research import ResearchRunner
    from verboisy.utils.config import Settings

    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        event = bound_event(store, rid, record_id)
        assert event["version"] == 2
        store.event(rid, "unit_normalization", event)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        observation = runner.dataset_comparability_observations()[0]
        assert observation["normalized_value"] == store.records(rid)[0]["population"] == 2000
        assert observation["canonical_unit"]["multiplier"] == 1


@pytest.mark.parametrize("field", ["candidate_key", "snapshot_id"])
def test_bound_event_rejects_stale_binding(tmp_path, field):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        payload = bound_event(store, rid, record_id)
        payload[field] = "stale"
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid)[0]["population"] == 2


def test_new_candidate_with_same_value_and_unit_does_not_inherit_bound_event(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        store.event(rid, "unit_normalization", bound_event(store, rid, record_id))
        accept_observation(
            store, rid, task, "thousands of persons", revision="second", preference="new"
        )
        assert store.records(rid)[0]["population"] == 2


def test_runner_produces_bound_events_idempotently(tmp_path):
    from verboisy.core.research import ResearchRunner
    from verboisy.utils.config import Settings

    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "thousands of persons")
        accept_observation(
            store, rid, task, "persons", revision="base", name="Beta", population=3000
        )
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        assert runner.ensure_unit_normalizations() == 1
        payload = store.events(rid, "unit_normalization")[0]["payload"]
        row = store.evidence(rid)[0]
        assert payload["version"] == 2
        assert payload["snapshot_id"] == row["snapshot"]["id"]
        assert payload["candidate_key"] == source_fitness_candidate_key(
            Candidate.model_validate(row["candidate"])
        )
        assert [row["population"] for row in store.records(rid)] == [2000, 3000]
        assert runner.ensure_unit_normalizations() == 0


@pytest.mark.parametrize("unit_label", ["widgets", "persons"])
def test_unknown_or_unscaled_source_never_authorizes_thousand_scale(tmp_path, unit_label):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, unit_label)
        persist_scale(store, rid, record_id)
        assert store.records(rid)[0]["population"] == 2


def test_missing_unit_metadata_keeps_original_value(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        payload = store.events(rid, "source_fitness")[0]["payload"]
        payload["claims"]["/population"]["comparability"]["definition"] = payload["claims"][
            "/population"
        ]["comparability"].pop("unit")
        store.event(rid, "source_fitness", payload)
        persist_scale(store, rid, record_id)
        assert store.records(rid)[0]["population"] == 2


def test_metadata_cannot_invent_a_nonexistent_pointer(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        payload = store.events(rid, "source_fitness")[0]["payload"]
        payload["claims"]["/missing"] = payload["claims"].pop("/population")
        store.event(rid, "source_fitness", payload)
        persist_scale(store, rid, record_id)
        assert store.records(rid)[0]["population"] == 2


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", True),
        ("version", 2.0),
        ("original_value", 2.0),
        ("normalized_value", 2000.0),
        ("multiplier", 1000.0),
        ("multiplier", True),
        ("canonical_unit", {"dimension": "count", "base_unit": "person", "multiplier": True}),
    ],
)
def test_replay_rejects_json_type_confusion(tmp_path, key, value):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        payload = bound_event(store, rid, record_id)
        payload[key] = value
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid)[0]["population"] == 2


def test_later_invalid_event_does_not_hide_earlier_valid_event(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        payload = bound_event(store, rid, record_id)
        store.event(rid, "unit_normalization", payload)
        payload["candidate_key"] = "stale"
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid)[0]["population"] == 2000


def test_bound_replay_survives_reopen_without_mutating_evidence(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "thousands of persons")
        raw = store.evidence(rid)
        store.event(rid, "unit_normalization", bound_event(store, rid, record_id))
        expected = store.records(rid)
    reopened = ResearchStore(str(tmp_path / "replay.db"))
    try:
        assert reopened.records(rid) == expected
        assert reopened.evidence(rid) == raw
    finally:
        reopened.close()
