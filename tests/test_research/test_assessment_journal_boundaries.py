# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Assessment replay must preserve deferred model access and journal failure order."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import (
    CandidateSourceAssessment,
    SourceAssessmentBatchResponse,
    source_assessment_cache_event,
    source_assessment_cache_key,
)
from verboisy.evidence.models import Candidate, Snapshot


@pytest.fixture
def assessment(monkeypatch):
    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T00:00:00Z",
        content_hash="hash",
        sources=[],
        truncated=False,
    )
    candidate = Candidate(scope="page", record={"value": "example"}, evidence={})
    response = SourceAssessmentBatchResponse(
        candidates=[CandidateSourceAssessment(candidate_index=0, assessments=[])]
    )
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.store = SimpleNamespace(events=MagicMock(return_value=[]), event=MagicMock())
    request = AsyncMock(return_value=response)
    monkeypatch.setattr("verboisy.core.research.assess_source_batch", request)
    return runner, page, candidate, response, request


async def test_cached_assessment_requires_no_client_or_goal(assessment):
    runner, page, candidate, response, request = assessment
    runner._source_assessment_events = [
        {
            "kind": "source_assessment_cache",
            "payload": source_assessment_cache_event(
                source_assessment_cache_key(page, [candidate]), response
            ),
        }
    ]
    assert not hasattr(runner, "client") and not hasattr(runner, "goal")
    assert (await runner.source_assess_candidates(page, [candidate]))[0]["/value"].grounded is False
    request.assert_not_awaited()
    runner.store.events.assert_not_called()
    assert runner.store.event.call_args.args[1] == "source_fitness"
    assert runner.store.event.call_args.args[2]["cache_hit"] is True


async def test_failed_cache_write_never_enters_invocation_cache(assessment):
    runner, page, candidate, _, request = assessment
    runner.client = SimpleNamespace()
    runner.goal = "Find example"
    runner.store.event.side_effect = OSError("ledger write failed")
    with pytest.raises(OSError, match="ledger write failed"):
        await runner.source_assess_candidates(page, [candidate])
    assert runner._source_assessment_events == []
    assert runner.store.event.call_args.args[1] == "source_assessment_cache"
    runner.store.event.side_effect = None
    assert (await runner.source_assess_candidates(page, [candidate]))[0]["/value"].grounded is False
    assert request.await_count == 2


async def test_failed_fitness_write_retains_persisted_response_for_retry(assessment):
    runner, page, candidate, _, request = assessment
    runner.client = SimpleNamespace()
    runner.goal = "Find example"
    runner.store.event.side_effect = [None, OSError("fitness write failed")]
    with pytest.raises(OSError, match="fitness write failed"):
        await runner.source_assess_candidates(page, [candidate])
    assert len(runner._source_assessment_events) == 1
    del runner.client
    del runner.goal
    runner.store.event.side_effect = None
    assert (await runner.source_assess_candidates(page, [candidate]))[0]["/value"].grounded is False
    request.assert_awaited_once()
    assert runner.store.event.call_args.args[2]["cache_hit"] is True
