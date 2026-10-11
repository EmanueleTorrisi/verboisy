# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import pytest
from verboisy.core.fitness import ClaimFitness
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Snapshot, Source
from verboisy.evidence.verify import verify
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


@pytest.fixture
def pair(tmp_path, request):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, request.param)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
        before = store.evidence(rid)[0]
        candidate = Candidate.model_validate(before["candidate"])
        previous = Snapshot.model_validate(before["snapshot"])
        quote = "Population unit: persons."
        refreshed = previous.model_copy(
            update={
                "id": "snapshot-unit-refresh",
                "url": "https://example.test/unit-refresh",
                "content_hash": "fixture-unit-refresh",
                "sources": [s for s in previous.sources if s.id != "unit"]
                + [Source(id="unit", kind="text", text=quote, scope="entity")],
            }
        )
        assert verify(candidate, refreshed, SCHEMA, task) == []
        store.queue(rid, refreshed.url, 0, None)
        work = store.next_page(rid)
        store.snapshot(rid, work["id"], refreshed, "fixture")
        response = SourceAssessmentResponse.model_validate(
            {
                "assessments": [
                    {
                        "pointer": "/population",
                        "unit": {
                            "label": "persons",
                            "citation": {"source": "unit", "quote": quote},
                        },
                    }
                ]
            }
        )
        claims = ground_source_assessments(candidate, refreshed, response)
        store.event(
            rid,
            "source_fitness",
            source_fitness_event(
                refreshed,
                candidate,
                claims,
                cache_key="refresh-fixture",
                cache_hit=False,
            ),
        )
        yield store, rid, runner, candidate, previous, refreshed


@pytest.mark.parametrize(
    "pair", ["widgets", "persons", "kg", "thousands of persons"], indirect=True
)
def test_unit_refresh_acceptance_and_reopen(pair):
    from verboisy.storage.research import ResearchStore

    store, rid, runner, candidate, previous, refreshed = pair
    before = store.evidence(rid)[0]
    comparison, mode = runner.compare_candidate_evidence(
        candidate, previous.id, candidate, refreshed.id
    )
    expected = "new" if previous.sources[-1].text == "Population unit: widgets." else "same"
    assert comparison.preference == expected
    assert mode == ("unit_repair" if expected == "new" else "source_fitness")
    outcome = store.accept(
        rid, refreshed, candidate, [], runner.task, preference=comparison.preference
    )
    assert outcome == ("accepted" if expected == "new" else "duplicate")
    after = store.evidence(rid)[0]
    assert after["record_id"] == before["record_id"]
    assert after["candidate"]["record"] == before["candidate"]["record"]
    assert after["snapshot"]["id"] == (refreshed.id if expected == "new" else previous.id)
    if expected == "new":
        assert runner.dataset_consistency_gaps() == ()
        assert runner.dataset_consistency_repairs() == ()
    path = store.db.execute("PRAGMA database_list").fetchone()[2]
    expected_evidence = store.evidence(rid)
    expected_records = store.records(rid)
    store.close()
    reopened = ResearchStore(path)
    try:
        assert reopened.evidence(rid) == expected_evidence
        assert reopened.records(rid) == expected_records
    finally:
        reopened.close()


@pytest.mark.parametrize("pair", ["widgets"], indirect=True)
@pytest.mark.parametrize(
    "case",
    [
        "values",
        "period",
        "loader",
        "old_snapshot",
        "new_snapshot",
        "quality",
        "no_policy",
        "not_sensitive",
        "not_comparable",
        "null",
        "missing_new_unit",
        "forged_unit",
        "definition_loss",
        "definition_change",
        "method_loss",
        "same_definition",
    ],
)
def test_unit_refresh_safeguards(pair, case, monkeypatch):
    from dataclasses import replace

    from verboisy.evidence.models import TemporalProof

    store, rid, runner, candidate, previous, refreshed = pair
    old = candidate.model_copy(deep=True)
    new = candidate.model_copy(deep=True)
    events = store.events(rid, "source_fitness")
    old_quality = {}
    new_quality = {}
    if case == "values":
        new.record["population"] = 3
    elif case == "period":
        new.temporal_evidence["/population"] = TemporalProof(
            source="unit", quote="2025", reference_year=2025
        )
    elif case == "loader":
        monkeypatch.setattr(store, "load_snapshot", None)
    elif case == "old_snapshot":
        previous = previous.model_copy(update={"id": "absent"})
    elif case == "new_snapshot":
        refreshed = refreshed.model_copy(update={"id": "absent"})
    elif case == "quality":
        old_quality["/name"] = ClaimFitness("/name", authority="responsible")
    elif case == "no_policy":
        runner.field_semantics = {}
    elif case in {"not_sensitive", "not_comparable"}:
        runner.field_semantics["/population"] = replace(
            runner.field_semantics["/population"],
            **{"unit_sensitive" if case == "not_sensitive" else "comparable_across_rows": False},
        )
    elif case == "null":
        old.record["population"] = new.record["population"] = None
    elif case in {"missing_new_unit", "forged_unit"}:
        claims = events[-1]["payload"]["claims"]
        if case == "missing_new_unit":
            claims.clear()
        else:
            claims["/population"]["comparability"]["unit"]["quote"] = "invented quote"
    else:
        attribute = "methodology_identity" if case == "method_loss" else "definition"
        descriptor = {"label": "Alba", "source": "name", "quote": "Alba"}
        events[0]["payload"]["claims"]["/population"]["comparability"][attribute] = descriptor
        if case == "same_definition":
            events[-1]["payload"]["claims"]["/population"]["comparability"][attribute] = descriptor
        elif case == "definition_change":
            events[-1]["payload"]["claims"]["/population"]["comparability"][attribute] = {
                "label": "first",
                "source": "revision",
                "quote": "first",
            }
    assert runner.unit_evidence_improves(
        old, previous.id, new, refreshed.id, events, old_quality, new_quality
    ) is (case == "same_definition")


@pytest.mark.parametrize("pair", ["widgets"], indirect=True)
def test_snapshot_lookup_is_run_scoped(pair):
    store, rid, runner, candidate, previous, refreshed = pair
    assert store.load_snapshot("another-run", previous.id) is None
    assert store.load_snapshot(rid, previous.id) == previous


@pytest.mark.parametrize("pair", ["widgets"], indirect=True)
async def test_runner_completes_after_processing_grounded_unit_repair(world, pair, monkeypatch):
    from unittest.mock import AsyncMock

    from verboisy.evidence.models import PageProposal, Proof

    from tests.test_research.test_contracts import PAGES

    store, rid, runner, candidate, previous, refreshed = pair
    runner.task.target_records = 1
    runner.task.settle_ms = 0
    runner.semantic_plan_ready = True
    before = store.records(rid)
    assert runner.target_met() is False
    monkeypatch.setitem(
        PAGES,
        refreshed.url,
        "<p>Alba</p><p>2</p><p>first</p><p>Population unit: persons.</p>",
    )

    async def propose(page, sources):
        observed = {source.text: source.id for source in sources}
        proposal = candidate.model_copy(deep=True)
        proposal.scope = "page"
        proposal.evidence = {
            "/" + key: Proof(
                source=observed[str(value)],
                quote=str(value),
                transform="integer" if key == "population" else "text",
            )
            for key, value in proposal.record.items()
        }
        return PageProposal(candidates=[proposal], priority_links=[])

    async def check(proposal, page):
        return verify(proposal, page, SCHEMA, runner.task)

    async def assess(page, candidates):
        unit_source = next(s for s in page.sources if s.text == "Population unit: persons.")
        response = SourceAssessmentResponse.model_validate(
            {
                "assessments": [
                    {
                        "pointer": "/population",
                        "unit": {
                            "label": "persons",
                            "citation": {
                                "source": unit_source.id,
                                "quote": unit_source.text,
                            },
                        },
                    }
                ]
            }
        )
        for proposal in candidates:
            grounded = ground_source_assessments(proposal, page, response)
            store.event(
                rid,
                "source_fitness",
                source_fitness_event(
                    page,
                    proposal,
                    grounded,
                    cache_key="runner-fixture",
                    cache_hit=False,
                ),
            )

    monkeypatch.setattr(runner.extractor, "propose", propose)
    monkeypatch.setattr(runner.extractor, "check", check)
    monkeypatch.setattr(runner, "source_assess_candidates", assess)
    provider = AsyncMock(side_effect=AssertionError("Unexpected model request"))
    monkeypatch.setattr(runner.client, "complete_json", provider)
    assert await runner.run(max_steps=1) == ("COMPLETED", "target_met")
    assert store.records(rid) == before
    assert runner.dataset_consistency_gaps() == ()
    assert runner.dataset_consistency_repairs() == ()
    assert store.evidence(rid)[0]["snapshot"]["url"] == refreshed.url
    assert (
        store.events(rid, "candidate_comparison")[-1]["payload"]["comparison_mode"] == "unit_repair"
    )
    provider.assert_not_awaited()
