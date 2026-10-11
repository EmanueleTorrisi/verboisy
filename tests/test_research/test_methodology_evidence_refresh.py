# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Missing methodology refresh must retain values and all existing evidence quality."""

from dataclasses import replace

import pytest
from verboisy.core.fitness import ClaimFitness
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.evidence.verify import verify
from verboisy.storage.research import ResearchStore

from tests.test_research import test_unit_evidence_refresh as unit_tests
from tests.test_storage.test_unit_replay_integrity import SCHEMA

pair = unit_tests.pair


@pytest.mark.parametrize("pair", ["persons"], indirect=True)
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "same",
        "different",
        "forged",
        "not_sensitive",
        "not_comparable",
        "quality",
        "unit_loss",
    ],
)
def test_methodology_refresh_is_grounded_and_conservative(pair, case):
    store, rid, runner, candidate, previous, refreshed = pair
    runner.task.target_records = 1
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"],
        methodology_sensitive=case != "not_sensitive",
        comparable_across_rows=case != "not_comparable",
    )
    descriptor = {"label": "first", "source": "revision", "quote": "first"}
    events = store.events(rid, "source_fitness")
    if case in {"same", "different"}:
        payload = events[0]["payload"]
        payload["claims"]["/population"]["comparability"]["methodology_identity"] = (
            descriptor if case == "same" else {"label": "Alba", "source": "name", "quote": "Alba"}
        )
        store.event(rid, "source_fitness", payload)
    payload = events[-1]["payload"]
    metadata = payload["claims"]["/population"]["comparability"]
    metadata["methodology_identity"] = (
        descriptor
        if case != "forged"
        else {
            "label": "invented",
            "source": "revision",
            "quote": "invented",
        }
    )
    if case == "unit_loss":
        metadata.pop("unit")
    store.event(rid, "source_fitness", payload)
    if case == "quality":
        old = events[0]["payload"]
        old["claims"]["/population"]["fitness"] = ClaimFitness(
            "/population", authority="responsible"
        ).as_event()
        store.event(rid, "source_fitness", old)
    before = store.records(rid)
    comparison, mode = runner.compare_candidate_evidence(
        candidate, previous.id, candidate, refreshed.id
    )
    expected = "new" if case == "missing" else "same"
    assert comparison.preference == expected
    assert mode == ("methodology_repair" if expected == "new" else "source_fitness")
    outcome = store.accept(
        rid, refreshed, candidate, [], runner.task, preference=comparison.preference
    )
    assert outcome == ("accepted" if expected == "new" else "duplicate")
    assert store.records(rid) == before
    assert store.evidence(rid)[0]["snapshot"]["id"] == (
        refreshed.id if expected == "new" else previous.id
    )
    if expected == "new":
        assert runner.target_met() is True
        assert runner.dataset_consistency_gaps() == ()
        assert runner.dataset_consistency_repairs() == ()
        evidence = store.evidence(rid)
        path = store.db.execute("PRAGMA database_list").fetchone()[2]
        store.close()
        reopened = ResearchStore(path)
        try:
            assert reopened.evidence(rid) == evidence
            assert reopened.records(rid) == before
        finally:
            reopened.close()


@pytest.mark.parametrize("pair", ["persons"], indirect=True)
async def test_runner_completes_after_processing_grounded_methodology_repair(
    world, pair, monkeypatch
):
    from unittest.mock import AsyncMock

    from verboisy.evidence.models import PageProposal, Proof

    from tests.test_research.test_contracts import PAGES

    store, rid, runner, candidate, previous, refreshed = pair
    runner.field_semantics["/population"] = replace(
        runner.field_semantics["/population"], methodology_sensitive=True
    )
    runner.task.target_records = 1
    runner.task.settle_ms = 0
    runner.semantic_plan_ready = True
    before = store.records(rid)
    assert runner.target_met() is False
    monkeypatch.setitem(
        PAGES,
        refreshed.url,
        "<p>Alba</p><p>2</p><p>first</p><p>Population unit: persons.</p><p>census count</p>",
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
                        "methodology_identity": {
                            "label": "census count",
                            "citation": {
                                "source": next(
                                    s.id for s in page.sources if s.text == "census count"
                                ),
                                "quote": "census count",
                            },
                        },
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
        store.events(rid, "candidate_comparison")[-1]["payload"]["comparison_mode"]
        == "methodology_repair"
    )
    provider.assert_not_awaited()
