# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Journal adapters cannot change source assessment replay through shared arguments."""

from asyncio import CancelledError
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from verboisy.core.assessment_journal import journal_candidate_assessments
from verboisy.core.source_assessment import (
    AssessmentCitation,
    CandidateSourceAssessment,
    ClaimSourceAssessment,
    SourceAssessmentBatchResponse,
    cached_source_assessment,
    source_assessment_cache_event,
    source_assessment_cache_key,
)

from tests.test_research.test_assessment_journal_boundaries import assessment

__all__ = ["assessment"]


@pytest.fixture
def response():
    return SourceAssessmentBatchResponse(
        candidates=[
            CandidateSourceAssessment(
                candidate_index=0,
                assessments=[
                    ClaimSourceAssessment(
                        pointer="/value",
                        authority="specialist",
                        citations=[AssessmentCitation(source="e1", quote="example")],
                    )
                ],
            )
        ]
    )


def damage(payload, level):
    if level == "key":
        payload["key"] = "changed"
    elif level == "version":
        payload["version"] = 999
    elif level == "response":
        payload["response"]["candidates"].clear()
    elif level == "claim":
        payload["response"]["candidates"][0]["assessments"][0]["authority"] = "general"
    else:
        payload["response"]["candidates"][0]["assessments"][0]["citations"][0]["quote"] = "changed"


@pytest.mark.parametrize("level", ["key", "version", "response", "claim", "citation"])
@pytest.mark.parametrize("when", ["during_write", "after_write"])
async def test_writer_mutations_do_not_change_retry_response(assessment, response, level, when):
    _, page, candidate, _, _ = assessment
    events = []
    retained = []
    request = AsyncMock(return_value=response)
    expected = response.model_dump(mode="json")
    key = source_assessment_cache_key(page, [candidate])

    def journal(kind, payload):
        assert kind == "source_assessment_cache"
        retained.append(payload)
        if when == "during_write":
            damage(payload, level)

    def ground(candidates, snapshot, supplied):
        assert candidates == [candidate] and snapshot == page
        assert supplied.model_dump(mode="json") == expected
        return []

    async def run():
        return await journal_candidate_assessments(
            page, [candidate], events, request, journal, ground, lambda: ()
        )

    assert await run() == []
    if when == "after_write":
        damage(retained[0], level)
    assert cached_source_assessment(events, key).model_dump(mode="json") == expected
    assert response.model_dump(mode="json") == expected
    assert await run() == []
    request.assert_awaited_once()
    assert len(retained) == len(events) == 1


@pytest.mark.parametrize("fault", [OSError, RuntimeError, KeyboardInterrupt, CancelledError])
async def test_mutated_failed_write_never_publishes_cache(assessment, response, fault):
    _, page, candidate, _, _ = assessment
    events = []
    retained = []
    request = AsyncMock(return_value=response)

    def failed_writer(kind, payload):
        retained.append(payload)
        damage(payload, "citation")
        raise fault("journal failed")

    with pytest.raises(fault, match="journal failed"):
        await journal_candidate_assessments(
            page, [candidate], events, request, failed_writer, lambda *_: [], lambda: ()
        )
    assert events == []
    await journal_candidate_assessments(
        page, [candidate], events, request, lambda *_: None, lambda *_: [], lambda: ()
    )
    assert request.await_count == 2 and len(events) == 1
    damage(retained[0], "response")
    assert (
        cached_source_assessment(events, source_assessment_cache_key(page, [candidate])) == response
    )


@pytest.mark.parametrize("kind", ["source_fitness", "search_request", "", None, True, 1, [], {}])
@pytest.mark.parametrize("older_valid", [False, True])
def test_explicit_other_event_kinds_never_supply_cached_response(response, kind, older_valid):
    valid = source_assessment_cache_event("key", response)
    events = [{"kind": "source_assessment_cache", "payload": valid}] if older_valid else []
    events.append(
        {
            "kind": kind,
            "payload": source_assessment_cache_event("key", SourceAssessmentBatchResponse()),
        }
    )
    before = deepcopy(events)
    assert cached_source_assessment(events, "key") == (response if older_valid else None)
    assert events == before


@pytest.mark.parametrize("typed", [False, True])
def test_legacy_and_current_cache_entries_remain_supported(response, typed):
    event = {"payload": source_assessment_cache_event("key", response)}
    if typed:
        event["kind"] = "source_assessment_cache"
    first = cached_source_assessment([event], "key")
    first.candidates[0].assessments[0].citations[0].quote = "changed"
    assert cached_source_assessment([event], "key") == response
