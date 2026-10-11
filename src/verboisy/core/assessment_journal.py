# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay assessment caches and journal grounded source fitness in candidate order.

Provider availability and invocation state belong to the runner. This workflow
borrows its event list and callbacks; it neither accepts candidates nor owns a
ledger or model client. Assessment failures retain the existing skip policy.
"""

from collections.abc import Awaitable, Callable
from copy import deepcopy

from pydantic import ValidationError

from verboisy.core.source_assessment import (
    GroundedClaimAssessment,
    SourceAssessmentBatchResponse,
    cached_source_assessment,
    source_assessment_cache_event,
    source_assessment_cache_key,
    source_fitness_event,
)
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.utils.exceptions import BudgetExceededError, LLMError


async def journal_candidate_assessments(
    page: Snapshot,
    candidates: list[Candidate],
    events: list[dict[str, object]],
    request: Callable[[], Awaitable[SourceAssessmentBatchResponse]],
    journal: Callable[[str, dict[str, object]], None],
    ground: Callable[
        [list[Candidate], Snapshot, SourceAssessmentBatchResponse],
        list[dict[str, GroundedClaimAssessment]],
    ],
    identity_fields: Callable[[], tuple[str, ...]],
) -> list[dict[str, GroundedClaimAssessment]]:
    """Reuse valid responses, then ground and journal without deciding acceptance."""
    key = source_assessment_cache_key(page, candidates)
    response = cached_source_assessment(events, key)
    cache_hit = response is not None
    if response is None:
        try:
            response = await request()
        except (BudgetExceededError, LLMError, ValidationError):
            journal(
                "source_assessment_skipped", {"url": page.url, "reason": "assessment_call_failed"}
            )
            return []
        payload = source_assessment_cache_event(key, response)
        # The writer may retain or mutate its arguments. Publish an independent
        # copy so successful writes cannot change later invocation replay.
        journal("source_assessment_cache", deepcopy(payload))
        # Replay in this invocation is valid only after the durable cache write succeeds.
        events.append({"kind": "source_assessment_cache", "payload": payload})
    try:
        grounded = ground(candidates, page, response)
    except ValueError:
        journal(
            "source_assessment_skipped",
            {"url": page.url, "reason": "invalid_grounding", "cache_key": key},
        )
        return []
    for index, claims in enumerate(grounded):
        journal(
            "source_fitness",
            source_fitness_event(
                page,
                candidates[index],
                claims,
                cache_key=key,
                cache_hit=cache_hit,
                identity_fields=identity_fields(),
            ),
        )
    return grounded
