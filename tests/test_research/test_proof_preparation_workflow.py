# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepared evidence is journaled before unchanged verification and semantic review."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.fitness import FieldSemantics
from verboisy.core.planner import TemporalIntent
from verboisy.core.proposal_review import review_page_proposal
from verboisy.evidence.models import Candidate, PageProposal, Snapshot, Source, TaskSpec
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.utils.exceptions import BudgetExceededError


def context():
    candidate = Candidate(
        scope="s",
        record={"name": "Example", "date": "2024-10-07"},
        evidence={
            "/name": {"source": "title", "quote": "Name: Example", "transform": "text"},
            "/date": {"source": "date", "quote": "2024-10-07", "transform": "text"},
        },
    )
    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-22",
        content_hash="fixture",
        truncated=False,
        sources=[
            Source(id="title", kind="text", scope="s", text="Name: Example"),
            Source(id="date", kind="text", scope="s", text="2024-10-07"),
        ],
    )
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "date": {"type": "string"}},
        "required": ["name", "date"],
        "additionalProperties": False,
    }
    client = SimpleNamespace(
        complete_json=AsyncMock(
            return_value={
                "relevant": True,
                "same_entity": True,
                "supported_fields": ["/name", "/date"],
                "rejected_fields": [],
            }
        )
    )
    runner = SimpleNamespace(
        rid="run",
        store=SimpleNamespace(event=MagicMock()),
        extractor=EvidenceExtractor(
            client,
            schema,
            TaskSpec(),
            "Find the event date",
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
            field_semantics={
                "/date": FieldSemantics(
                    pointer="/date", temporal_class="event", reference_period="required"
                )
            },
        ),
        source_assess_candidates=AsyncMock(),
    )
    return runner, candidate, page, client


async def review(runner, candidate, page, supplied=None):
    return await review_page_proposal(
        runner,
        page,
        page if supplied is None else supplied,
        PageProposal(candidates=[candidate]),
        MagicMock(return_value=None),
        MagicMock(return_value=[]),
        MagicMock(return_value=None),
    )


async def test_journal_retains_original_and_prepared_candidate_before_review():
    runner, candidate, page, client = context()
    original = candidate.model_dump(mode="json")
    order = []
    runner.store.event.side_effect = lambda _rid, kind, _payload: order.append(kind)

    async def audit(*args):
        order.append("semantic_review")
        return {
            "relevant": True,
            "same_entity": True,
            "supported_fields": ["/name", "/date"],
            "rejected_fields": [],
        }

    client.complete_json.side_effect = audit
    checked = await review(runner, candidate, page)
    assert order == ["extraction_proposal", "evidence_preparation", "semantic_review"]
    assert candidate.model_dump(mode="json") == original
    prepared, errors = checked[0]
    assert not errors and prepared.record == candidate.record
    calls = runner.store.event.call_args_list
    assert calls[0].args[2]["proposal"]["candidates"][0] == original
    assert calls[1].args[2]["candidate"] == prepared.model_dump(mode="json")
    assert calls[1].args[2]["candidate_index"] == 0
    assert len(calls[1].args[2]["changes"]) == 2
    runner.source_assess_candidates.assert_awaited_once_with(page, [prepared])
    client.complete_json.assert_awaited_once()


async def test_failed_preparation_journal_stops_before_model_or_assessment():
    runner, candidate, page, client = context()
    runner.store.event.side_effect = [None, OSError("Journal unavailable")]
    with pytest.raises(OSError, match="Journal unavailable"):
        await review(runner, candidate, page)
    client.complete_json.assert_not_awaited()
    runner.source_assess_candidates.assert_not_awaited()


async def test_semantic_rejection_is_not_overridden_by_literal_preparation():
    runner, candidate, page, client = context()
    client.complete_json.return_value = {
        "relevant": False,
        "same_entity": True,
        "supported_fields": [],
        "rejected_fields": ["/name", "/date"],
    }
    checked = await review(runner, candidate, page)
    assert checked[0][1] == ["semantic_review_rejected"]
    runner.source_assess_candidates.assert_not_awaited()
    client.complete_json.assert_awaited_once()


async def test_budget_stop_propagates_without_retry_or_acceptance():
    runner, candidate, page, client = context()
    client.complete_json.side_effect = BudgetExceededError("Budget exhausted")
    with pytest.raises(BudgetExceededError):
        await review(runner, candidate, page)
    client.complete_json.assert_awaited_once()
    runner.source_assess_candidates.assert_not_awaited()


async def test_preparation_uses_only_supplied_batch_not_other_captured_sources():
    runner, candidate, page, client = context()
    supplied = page.model_copy(update={"sources": [page.sources[0]]})
    checked = await review(runner, candidate, page, supplied)
    assert "/date:source_outside_entity" in checked[0][1]
    assert checked[0][0].temporal_evidence == {}
    client.complete_json.assert_not_awaited()
    runner.source_assess_candidates.assert_not_awaited()


async def test_absent_values_stay_rejected_without_a_preparation_event():
    runner, candidate, page, client = context()
    candidate.record = {"name": "Invented"}
    candidate.evidence.pop("/date")
    checked = await review(runner, candidate, page)
    assert checked[0][0] is candidate and checked[0][1]
    assert [call.args[1] for call in runner.store.event.call_args_list] == ["extraction_proposal"]
    client.complete_json.assert_not_awaited()
