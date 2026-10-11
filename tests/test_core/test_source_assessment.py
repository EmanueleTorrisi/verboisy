# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import pytest
from pydantic import ValidationError
from verboisy.core.source_assessment import (
    AssessmentCitation,
    ClaimSourceAssessment,
    SourceAssessmentResponse,
    ground_source_assessments,
)
from verboisy.evidence.models import (
    Candidate,
    Snapshot,
    Source,
    TemporalProof,
)


def candidate():
    return Candidate(
        scope="s1",
        record={
            "name": "Example",
            "population": 100,
            "optional": None,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e2",
                quote="Population 2025",
                reference_year=2025,
            )
        },
    )


def page():
    return Snapshot(
        id="snapshot",
        url="https://example.test/data",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[
            Source(
                id="e1",
                kind="text",
                text=(
                    "Official statistical agency "
                    "publishes this dataset using "
                    "the documented annual census "
                    "methodology."
                ),
                scope="page",
            ),
            Source(
                id="e2",
                kind="text",
                text=("Example Population 2025: 100"),
                scope="s1",
            ),
            Source(
                id="other",
                kind="text",
                text="Unrelated article",
                scope="s2",
            ),
        ],
        truncated=False,
    )


def assessment(
    pointer="/population",
    *,
    citations=None,
    authority="responsible",
    directness="primary",
    methodology="explicit",
    provenance="traceable",
):
    return ClaimSourceAssessment(
        pointer=pointer,
        authority=authority,
        directness=directness,
        methodology=methodology,
        provenance=provenance,
        citations=(
            citations
            if citations is not None
            else [
                AssessmentCitation(
                    source="e1",
                    quote=("Official statistical " "agency publishes this " "dataset"),
                )
            ]
        ),
    )


def test_grounded_assessment_builds_claim_fitness():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(assessments=[assessment()]),
    )

    population = result["/population"]

    assert population.grounded
    assert population.reason is None
    assert population.citation_sources == ("e1",)
    assert population.fitness.authority == "responsible"
    assert population.fitness.directness == "primary"
    assert population.fitness.methodology == "explicit"
    assert population.fitness.provenance == "traceable"
    assert population.fitness.corroboration == 0
    assert population.fitness.reference_year == 2025

    assert result["/name"].reason == ("missing_source_assessment")


def test_grounded_assessment_event_is_auditable():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(assessments=[assessment()]),
    )

    event = result["/population"].as_event()

    assert event["pointer"] == "/population"
    assert event["grounded"] is True
    assert event["citation_sources"] == ["e1"]
    assert event["fitness"]["reference_year"] == 2025


def test_optional_null_field_is_not_assessed():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(),
    )

    assert "/optional" not in result


def test_unknown_pointer_is_rejected():
    with pytest.raises(
        ValueError,
        match=("unknown_source_assessment_pointer"),
    ):
        ground_source_assessments(
            candidate(),
            page(),
            SourceAssessmentResponse(assessments=[assessment(pointer="/missing")]),
        )


def test_duplicate_pointer_is_rejected():
    item = assessment()

    with pytest.raises(
        ValueError,
        match=("duplicate_source_assessment_pointer"),
    ):
        ground_source_assessments(
            candidate(),
            page(),
            SourceAssessmentResponse(
                assessments=[
                    item,
                    item,
                ]
            ),
        )


@pytest.mark.parametrize(
    "citations",
    [
        [],
        [
            AssessmentCitation(
                source="missing",
                quote="text",
            )
        ],
        [
            AssessmentCitation(
                source="other",
                quote="Unrelated article",
            )
        ],
        [
            AssessmentCitation(
                source="e1",
                quote="not observed",
            )
        ],
        [
            AssessmentCitation(
                source="e1",
                quote="   ",
            )
        ],
    ],
)
def test_unverified_assessment_collapses_to_unknown(
    citations,
):
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(assessments=[assessment(citations=citations)]),
    )

    item = result["/population"]

    assert not item.grounded
    assert item.reason == ("ungrounded_source_assessment")
    assert item.fitness.authority == "unknown"
    assert item.fitness.directness == "unknown"
    assert item.fitness.methodology == "unknown"
    assert item.fitness.provenance == "unknown"

    # Deterministic temporal provenance is
    # preserved even when source fitness fails.
    assert item.fitness.reference_year == 2025


def test_duplicate_citation_source_is_deduplicated():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(
            assessments=[
                assessment(
                    citations=[
                        AssessmentCitation(
                            source="e1",
                            quote=("Official statistical " "agency"),
                        ),
                        AssessmentCitation(
                            source="e1",
                            quote=("annual census " "methodology"),
                        ),
                    ]
                )
            ]
        ),
    )

    assert result["/population"].citation_sources == ("e1",)


def test_entity_scoped_assessment_citation_is_allowed():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(
            assessments=[
                assessment(
                    citations=[
                        AssessmentCitation(
                            source="e2",
                            quote=("Example Population " "2025"),
                        )
                    ]
                )
            ]
        ),
    )

    assert result["/population"].grounded


def test_all_unknown_assessment_needs_no_citation():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(
            assessments=[
                assessment(
                    citations=[],
                    authority="unknown",
                    directness="unknown",
                    methodology="unknown",
                    provenance="unknown",
                )
            ]
        ),
    )

    item = result["/population"]

    assert item.grounded
    assert item.reason is None
    assert item.fitness.authority == "unknown"


def test_absent_and_opaque_do_not_gain_quality_credit():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(
            assessments=[
                assessment(
                    citations=[],
                    authority="unknown",
                    directness="unknown",
                    methodology="absent",
                    provenance="opaque",
                )
            ]
        ),
    )

    item = result["/population"]

    assert item.grounded
    assert item.fitness.methodology == "unknown"
    assert item.fitness.provenance == "unknown"


def test_static_field_has_no_reference_year():
    result = ground_source_assessments(
        candidate(),
        page(),
        SourceAssessmentResponse(assessments=[assessment(pointer="/name")]),
    )

    assert result["/name"].fitness.reference_year is None


def test_assessment_models_are_strict():
    with pytest.raises(ValidationError):
        AssessmentCitation.model_validate(
            {
                "source": "e1",
                "quote": "text",
                "invented": True,
            }
        )


def test_ground_source_assessment_batch_preserves_candidate_order():
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
        ground_source_assessment_batch,
    )

    first = candidate()
    second = Candidate(
        scope="s1",
        record={
            "name": "Second",
            "population": 200,
        },
        evidence={},
        temporal_evidence={},
    )

    response = SourceAssessmentBatchResponse(
        candidates=[
            CandidateSourceAssessment(
                candidate_index=1,
                assessments=[assessment(pointer="/population")],
            ),
            CandidateSourceAssessment(
                candidate_index=0,
                assessments=[assessment(pointer="/population")],
            ),
        ]
    )

    result = ground_source_assessment_batch(
        [first, second],
        page(),
        response,
    )

    assert len(result) == 2
    assert result[0]["/population"].grounded
    assert result[1]["/population"].grounded

    assert result[0]["/population"].fitness.reference_year == 2025
    assert result[1]["/population"].fitness.reference_year is None


def test_missing_candidate_batch_entry_becomes_unknown():
    from verboisy.core.source_assessment import (
        SourceAssessmentBatchResponse,
        ground_source_assessment_batch,
    )

    result = ground_source_assessment_batch(
        [candidate()],
        page(),
        SourceAssessmentBatchResponse(),
    )

    assert result[0]["/population"].reason == ("missing_source_assessment")


def test_unknown_candidate_batch_index_is_rejected():
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
        ground_source_assessment_batch,
    )

    with pytest.raises(
        ValueError,
        match=("unknown_source_assessment_candidate"),
    ):
        ground_source_assessment_batch(
            [candidate()],
            page(),
            SourceAssessmentBatchResponse(
                candidates=[CandidateSourceAssessment(candidate_index=1)]
            ),
        )


def test_duplicate_candidate_batch_index_is_rejected():
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
        ground_source_assessment_batch,
    )

    item = CandidateSourceAssessment(candidate_index=0)

    with pytest.raises(
        ValueError,
        match=("duplicate_source_assessment_candidate"),
    ):
        ground_source_assessment_batch(
            [candidate()],
            page(),
            SourceAssessmentBatchResponse(
                candidates=[
                    item,
                    item,
                ]
            ),
        )


@pytest.mark.asyncio
async def test_assess_source_batch_uses_one_model_call():
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verboisy.core.source_assessment import (
        assess_source_batch,
    )

    client = SimpleNamespace(
        complete_json=AsyncMock(
            return_value={
                "candidates": [
                    {
                        "candidate_index": 0,
                        "assessments": [],
                    }
                ]
            }
        )
    )

    result = await assess_source_batch(
        client,
        goal="Find population",
        page=page(),
        candidates=[candidate()],
    )

    assert len(result.candidates) == 1

    client.complete_json.assert_awaited_once()

    payload = json.loads(client.complete_json.await_args.args[1])

    assert len(payload["candidates"]) == 1

    assert payload["candidates"][0]["candidate_index"] == 0

    source_ids = {source["id"] for source in payload["sources"]}

    assert "e1" in source_ids
    assert "e2" in source_ids

    # Cross-entity content is excluded before
    # reaching the assessment model.
    assert "other" not in source_ids


@pytest.mark.asyncio
async def test_assess_empty_source_batch_uses_no_model():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verboisy.core.source_assessment import (
        assess_source_batch,
    )

    client = SimpleNamespace(complete_json=AsyncMock())

    result = await assess_source_batch(
        client,
        goal="Find",
        page=page(),
        candidates=[],
    )

    assert result.candidates == []
    client.complete_json.assert_not_awaited()


def test_source_assessment_batch_model_is_strict():
    from verboisy.core.source_assessment import (
        SourceAssessmentBatchResponse,
    )

    with pytest.raises(ValidationError):
        SourceAssessmentBatchResponse.model_validate(
            {
                "candidates": [],
                "invented": True,
            }
        )


def test_source_assessment_cache_key_is_deterministic():
    from verboisy.core.source_assessment import (
        source_assessment_cache_key,
    )

    first = source_assessment_cache_key(
        page(),
        [candidate()],
    )
    second = source_assessment_cache_key(
        page(),
        [candidate()],
    )

    assert first == second
    assert len(first) == 64


def test_source_assessment_cache_key_changes_with_candidate():
    from verboisy.core.source_assessment import (
        source_assessment_cache_key,
    )

    changed = Candidate(
        scope="s1",
        record={
            "name": "Example",
            "population": 101,
        },
        evidence={},
        temporal_evidence={},
    )

    assert source_assessment_cache_key(
        page(),
        [candidate()],
    ) != source_assessment_cache_key(
        page(),
        [changed],
    )


def test_source_assessment_cache_key_changes_with_page_content():
    from verboisy.core.source_assessment import (
        source_assessment_cache_key,
    )

    changed_page = page().model_copy(
        update={
            "content_hash": "changed",
        }
    )

    assert source_assessment_cache_key(
        page(),
        [candidate()],
    ) != source_assessment_cache_key(
        changed_page,
        [candidate()],
    )


def test_source_assessment_cache_ignores_other_entity_sources():
    from verboisy.core.source_assessment import (
        source_assessment_cache_key,
    )

    original = page()

    changed_sources = [
        source.model_copy(update={"text": "Changed unrelated text"})
        if source.id == "other"
        else source
        for source in original.sources
    ]

    changed_page = original.model_copy(
        update={
            "sources": changed_sources,
        }
    )

    # The unrelated entity is not sent to the
    # assessor, so changing it cannot invalidate
    # the paid assessment.
    assert source_assessment_cache_key(
        original,
        [candidate()],
    ) == source_assessment_cache_key(
        changed_page,
        [candidate()],
    )


def test_source_assessment_cache_event_round_trip():
    from verboisy.core.source_assessment import (
        CandidateSourceAssessment,
        SourceAssessmentBatchResponse,
        cached_source_assessment,
        source_assessment_cache_event,
    )

    response = SourceAssessmentBatchResponse(
        candidates=[
            CandidateSourceAssessment(
                candidate_index=0,
                assessments=[assessment()],
            )
        ]
    )

    payload = source_assessment_cache_event(
        "cache-key",
        response,
    )

    cached = cached_source_assessment(
        [
            {
                "kind": ("source_assessment_cache"),
                "payload": payload,
            }
        ],
        "cache-key",
    )

    assert cached == response


def test_source_assessment_cache_miss_returns_none():
    from verboisy.core.source_assessment import (
        cached_source_assessment,
    )

    assert (
        cached_source_assessment(
            [],
            "missing",
        )
        is None
    )


def test_source_assessment_cache_ignores_wrong_key_and_version():
    from verboisy.core.source_assessment import (
        cached_source_assessment,
    )

    events = [
        {
            "payload": {
                "version": 1,
                "key": "other",
                "response": {"candidates": []},
            }
        },
        {
            "payload": {
                "version": 999,
                "key": "wanted",
                "response": {"candidates": []},
            }
        },
    ]

    assert (
        cached_source_assessment(
            events,
            "wanted",
        )
        is None
    )


def test_source_assessment_cache_skips_corrupt_newest_entry():
    from verboisy.core.source_assessment import (
        SourceAssessmentBatchResponse,
        cached_source_assessment,
        source_assessment_cache_event,
    )

    valid = SourceAssessmentBatchResponse()

    events = [
        {
            "payload": (
                source_assessment_cache_event(
                    "wanted",
                    valid,
                )
            )
        },
        {
            "payload": {
                "version": 1,
                "key": "wanted",
                "response": {
                    "not_candidates": True,
                },
            }
        },
    ]

    assert (
        cached_source_assessment(
            events,
            "wanted",
        )
        == valid
    )


def test_source_assessment_cache_ignores_non_mapping_payload():
    from verboisy.core.source_assessment import (
        cached_source_assessment,
    )

    assert (
        cached_source_assessment(
            [
                {
                    "payload": "invalid",
                }
            ],
            "wanted",
        )
        is None
    )


def test_source_fitness_candidate_key_is_stable():
    from verboisy.core.source_assessment import (
        source_fitness_candidate_key,
    )

    assert source_fitness_candidate_key(candidate()) == source_fitness_candidate_key(candidate())


def test_source_fitness_candidate_key_changes_with_candidate():
    from verboisy.core.source_assessment import (
        source_fitness_candidate_key,
    )

    changed = candidate().model_copy(
        update={
            "record": {
                "name": "Example",
                "population": 101,
                "optional": None,
            }
        }
    )

    assert source_fitness_candidate_key(candidate()) != source_fitness_candidate_key(changed)


def test_source_fitness_event_round_trip():
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
        source_fitness_from_events,
    )

    claim = GroundedClaimAssessment(
        pointer="/population",
        fitness=_strong_claim_fitness(),
        grounded=True,
        reason=None,
        citation_sources=("e1",),
    )

    payload = source_fitness_event(
        page(),
        candidate(),
        {
            "/population": claim,
        },
        cache_key="cache",
        cache_hit=False,
    )

    result = source_fitness_from_events(
        [
            {
                "kind": "source_fitness",
                "payload": payload,
            }
        ],
        snapshot_id="snapshot",
        candidate=candidate(),
    )

    assert result is not None
    assert result["/population"] == claim.fitness


def _strong_claim_fitness():
    from verboisy.core.fitness import (
        ClaimFitness,
    )

    return ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=1,
        reference_year=2025,
    )


def test_source_fitness_lookup_requires_snapshot_match():
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
        source_fitness_from_events,
    )

    payload = source_fitness_event(
        page(),
        candidate(),
        {
            "/population": (
                GroundedClaimAssessment(
                    pointer="/population",
                    fitness=(_strong_claim_fitness()),
                    grounded=True,
                    reason=None,
                    citation_sources=("e1",),
                )
            )
        },
        cache_key="cache",
        cache_hit=False,
    )

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="different",
            candidate=candidate(),
        )
        is None
    )


def test_source_fitness_lookup_skips_corrupt_newest():
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
        source_fitness_from_events,
    )

    valid = source_fitness_event(
        page(),
        candidate(),
        {
            "/population": (
                GroundedClaimAssessment(
                    pointer="/population",
                    fitness=(_strong_claim_fitness()),
                    grounded=True,
                    reason=None,
                    citation_sources=("e1",),
                )
            )
        },
        cache_key="cache",
        cache_hit=False,
    )

    corrupt = dict(valid)
    corrupt["claims"] = {
        "/population": {
            "fitness": {
                **_strong_claim_fitness().as_event(),
                "pointer": "/wrong",
            }
        }
    }

    result = source_fitness_from_events(
        [
            {"payload": valid},
            {"payload": corrupt},
        ],
        snapshot_id="snapshot",
        candidate=candidate(),
    )

    assert result is not None
    assert result["/population"].pointer == "/population"


def test_source_fitness_lookup_ignores_bad_payload():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    assert (
        source_fitness_from_events(
            [
                {"payload": "bad"},
                {
                    "payload": {
                        "version": 1,
                        "snapshot_id": "snapshot",
                        "candidate_key": "wrong",
                    }
                },
            ],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def _source_fitness_payload_with_claims(claims):
    from verboisy.core.source_assessment import (
        SOURCE_FITNESS_EVENT_VERSION,
        source_fitness_candidate_key,
    )

    return {
        "version": SOURCE_FITNESS_EVENT_VERSION,
        "snapshot_id": "snapshot",
        "candidate_key": (source_fitness_candidate_key(candidate())),
        "claims": claims,
    }


def test_source_fitness_lookup_skips_non_mapping_claims():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    payload = _source_fitness_payload_with_claims(["invalid"])

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def test_source_fitness_lookup_skips_non_string_pointer():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    payload = _source_fitness_payload_with_claims(
        {123: {"fitness": (_strong_claim_fitness().as_event())}}
    )

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def test_source_fitness_lookup_skips_non_mapping_assessment():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    payload = _source_fitness_payload_with_claims(
        {
            "/population": "invalid",
        }
    )

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def test_source_fitness_lookup_skips_non_mapping_fitness():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    payload = _source_fitness_payload_with_claims({"/population": {"fitness": "invalid"}})

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def test_source_fitness_lookup_skips_pointer_mismatch():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    fitness = {
        **_strong_claim_fitness().as_event(),
        "pointer": "/wrong",
    }

    payload = _source_fitness_payload_with_claims(
        {
            "/population": {
                "fitness": fitness,
            }
        }
    )

    assert (
        source_fitness_from_events(
            [{"payload": payload}],
            snapshot_id="snapshot",
            candidate=candidate(),
        )
        is None
    )


def _origin_candidate():
    from verboisy.evidence.models import (
        Candidate,
    )

    return Candidate(
        scope="entity-1",
        record={
            "name": "Example",
        },
        evidence={},
        temporal_evidence={},
    )


def _origin_page(
    *,
    scope="entity-1",
    quote=("Source: World Health Organization"),
    href=("https://www.who.int/data/report"),
):
    from verboisy.evidence.models import (
        Snapshot,
        Source,
    )

    return Snapshot(
        id="origin-snapshot",
        url="https://example.test/report",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="origin-hash",
        sources=[
            Source(
                id="origin-evidence",
                kind="link",
                text=quote,
                scope=scope,
                href=href,
            )
        ],
        truncated=False,
    )


def _origin_response(
    *,
    label="World Health Organization",
    quote=("Source: World Health Organization"),
    source="origin-evidence",
):
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        OriginAttribution,
        SourceAssessmentResponse,
    )

    return SourceAssessmentResponse(
        assessments=[
            ClaimSourceAssessment(
                pointer="/name",
                authority="unknown",
                directness="unknown",
                methodology="unknown",
                provenance="unknown",
                citations=[],
                origin=OriginAttribution(
                    label=label,
                    citation=AssessmentCitation(
                        source=source,
                        quote=quote,
                    ),
                ),
            )
        ]
    )


def test_grounded_origin_is_attached_to_claim_assessment():
    from verboisy.core.source_assessment import (
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _origin_candidate(),
        _origin_page(),
        _origin_response(),
    )

    identity = result["/name"].provenance_identity

    assert identity is not None
    assert identity.kind == "attribution_host"
    assert identity.host == "who.int"


def test_ungrounded_origin_quote_is_ignored():
    from verboisy.core.source_assessment import (
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _origin_candidate(),
        _origin_page(),
        _origin_response(quote=("Source: UNICEF")),
    )

    assert result["/name"].provenance_identity is None


def test_origin_outside_candidate_scope_is_ignored():
    from verboisy.core.source_assessment import (
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _origin_candidate(),
        _origin_page(scope="other-entity"),
        _origin_response(),
    )

    assert result["/name"].provenance_identity is None


def test_missing_origin_source_is_ignored():
    from verboisy.core.source_assessment import (
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _origin_candidate(),
        _origin_page(),
        _origin_response(source="missing"),
    )

    assert result["/name"].provenance_identity is None


def test_no_origin_preserves_old_event_shape():
    from verboisy.core.source_assessment import (
        ClaimSourceAssessment,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _origin_candidate(),
        _origin_page(),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/name",
                    authority="unknown",
                    directness="unknown",
                    methodology="unknown",
                    provenance="unknown",
                    citations=[],
                )
            ]
        ),
    )

    event = result["/name"].as_event()

    assert "provenance_identity" not in event


def test_grounded_origin_is_persisted_in_source_fitness_event():
    from verboisy.core.source_assessment import (
        ground_source_assessments,
        source_fitness_event,
    )

    candidate = _origin_candidate()
    page = _origin_page()

    grounded = ground_source_assessments(
        candidate,
        page,
        _origin_response(),
    )

    event = source_fitness_event(
        page,
        candidate,
        grounded,
        cache_key="cache",
        cache_hit=False,
    )

    provenance = event["claims"]["/name"]["provenance_identity"]

    assert provenance["kind"] == "attribution_host"
    assert provenance["host"] == "who.int"
    assert len(provenance["key"]) == 64


def test_cached_source_assessment_skips_invalid_matching_response():
    from verboisy.core.source_assessment import (
        SOURCE_ASSESSMENT_CACHE_VERSION,
        cached_source_assessment,
    )

    events = [
        {
            "payload": {
                "version": (SOURCE_ASSESSMENT_CACHE_VERSION),
                "key": "wanted",
                "response": {"candidates": "invalid"},
            }
        }
    ]

    assert (
        cached_source_assessment(
            events,
            "wanted",
        )
        is None
    )


def test_source_fitness_event_records_entity_and_value_keys():
    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    claims = {
        "/population": (
            GroundedClaimAssessment(
                pointer="/population",
                fitness=ClaimFitness(pointer="/population"),
                grounded=True,
                reason=None,
                citation_sources=(),
            )
        )
    }

    event = source_fitness_event(
        page,
        candidate,
        claims,
        cache_key="cache",
        cache_hit=False,
        identity_fields=("/name",),
    )

    assert len(event["entity_key"]) == 64

    claim = event["claims"]["/population"]

    assert len(claim["value_key"]) == 64


def test_source_fitness_event_without_identity_keeps_legacy_shape():
    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    event = source_fitness_event(
        page,
        candidate,
        {
            "/name": (
                GroundedClaimAssessment(
                    pointer="/name",
                    fitness=ClaimFitness(pointer="/name"),
                    grounded=True,
                    reason=None,
                    citation_sources=(),
                )
            )
        },
        cache_key="cache",
        cache_hit=False,
    )

    assert "entity_key" not in event

    assert "value_key" not in event["claims"]["/name"]


def test_source_fitness_event_skips_value_key_for_unknown_claim_pointer():
    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
        },
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="hash",
        sources=[],
        truncated=False,
    )

    event = source_fitness_event(
        page,
        candidate,
        {
            "/missing": (
                GroundedClaimAssessment(
                    pointer="/missing",
                    fitness=ClaimFitness(pointer="/missing"),
                    grounded=True,
                    reason=None,
                    citation_sources=(),
                )
            )
        },
        cache_key="cache",
        cache_hit=False,
        identity_fields=("/name",),
    )

    assert "value_key" not in event["claims"]["/missing"]


def _corroboration_observation(
    *,
    snapshot_id,
    label,
    host,
    value=100,
    reference_year=2025,
    grounded=True,
):
    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.provenance import (
        provenance_identity,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
        Source,
    )

    source = Source(
        id=f"source-{snapshot_id}",
        kind="link",
        text=f"Source: {label}",
        scope="entity",
        href=f"https://{host}/data",
    )

    origin = provenance_identity(
        source,
        label=label,
        quote=f"Source: {label}",
    )

    assert origin is not None

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": value,
        },
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id=snapshot_id,
        url=f"https://page-{snapshot_id}.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash=f"hash-{snapshot_id}",
        sources=[source],
        truncated=False,
    )

    claims = {
        "/population": (
            GroundedClaimAssessment(
                pointer="/population",
                fitness=ClaimFitness(
                    pointer="/population",
                    authority="general",
                    reference_year=(reference_year),
                ),
                grounded=grounded,
                reason=None,
                citation_sources=(source.id,),
                provenance_identity=origin,
            )
        )
    }

    event = source_fitness_event(
        page,
        candidate,
        claims,
        cache_key=f"cache-{snapshot_id}",
        cache_hit=False,
        identity_fields=("/name",),
    )

    return (
        candidate,
        {
            "payload": event,
        },
    )


def test_source_fitness_counts_independent_grounded_origin():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    _, first = _corroboration_observation(
        snapshot_id="one",
        label="Agency A",
        host="agency-a.example",
    )

    candidate, second = _corroboration_observation(
        snapshot_id="two",
        label="Agency B",
        host="agency-b.example",
    )

    fitness = source_fitness_from_events(
        [
            first,
            second,
        ],
        snapshot_id="two",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 1


def test_source_fitness_does_not_count_same_origin():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    _, first = _corroboration_observation(
        snapshot_id="one",
        label="Agency A",
        host="agency-a.example",
    )

    candidate, second = _corroboration_observation(
        snapshot_id="two",
        label="Agency A",
        host="agency-a.example",
    )

    fitness = source_fitness_from_events(
        [
            first,
            second,
        ],
        snapshot_id="two",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 0


def test_source_fitness_does_not_corroborate_different_value():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    _, first = _corroboration_observation(
        snapshot_id="one",
        label="Agency A",
        host="agency-a.example",
        value=99,
    )

    candidate, second = _corroboration_observation(
        snapshot_id="two",
        label="Agency B",
        host="agency-b.example",
        value=100,
    )

    fitness = source_fitness_from_events(
        [
            first,
            second,
        ],
        snapshot_id="two",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 0


def test_source_fitness_does_not_corroborate_different_period():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    _, first = _corroboration_observation(
        snapshot_id="one",
        label="Agency A",
        host="agency-a.example",
        reference_year=2024,
    )

    candidate, second = _corroboration_observation(
        snapshot_id="two",
        label="Agency B",
        host="agency-b.example",
        reference_year=2025,
    )

    fitness = source_fitness_from_events(
        [
            first,
            second,
        ],
        snapshot_id="two",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 0


def test_source_fitness_ignores_ungrounded_corroborator():
    from verboisy.core.source_assessment import (
        source_fitness_from_events,
    )

    _, first = _corroboration_observation(
        snapshot_id="one",
        label="Agency A",
        host="agency-a.example",
        grounded=False,
    )

    candidate, second = _corroboration_observation(
        snapshot_id="two",
        label="Agency B",
        host="agency-b.example",
    )

    fitness = source_fitness_from_events(
        [
            first,
            second,
        ],
        snapshot_id="two",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 0


def test_legacy_source_fitness_remains_usable_without_corroboration_metadata():
    from verboisy.core.fitness import (
        ClaimFitness,
    )
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        source_fitness_event,
        source_fitness_from_events,
    )
    from verboisy.evidence.models import (
        Candidate,
        Snapshot,
    )

    candidate = Candidate(
        scope="entity",
        record={
            "name": "Example",
            "population": 100,
        },
        evidence={},
        temporal_evidence={},
    )

    page = Snapshot(
        id="legacy",
        url="https://example.test/",
        fetched_at=("2026-10-01T12:00:00+00:00"),
        content_hash="legacy-hash",
        sources=[],
        truncated=False,
    )

    event = source_fitness_event(
        page,
        candidate,
        {
            "/population": (
                GroundedClaimAssessment(
                    pointer="/population",
                    fitness=ClaimFitness(
                        pointer="/population",
                        authority="general",
                        reference_year=2025,
                    ),
                    grounded=True,
                    reason=None,
                    citation_sources=(),
                )
            )
        },
        cache_key="legacy-cache",
        cache_hit=False,
    )

    fitness = source_fitness_from_events(
        [
            {
                "payload": event,
            }
        ],
        snapshot_id="legacy",
        candidate=candidate,
    )

    assert fitness is not None

    assert fitness["/population"].corroboration == 0


def _patch_runtime_fitness_base(
    monkeypatch,
):
    import verboisy.core.source_assessment as module
    from verboisy.core.fitness import ClaimFitness

    expected = {
        "/population": ClaimFitness(
            pointer="/population",
            authority="general",
            reference_year=2025,
        )
    }

    def fake_base(
        events,
        *,
        snapshot_id,
        candidate,
    ):
        return expected

    monkeypatch.setattr(
        module,
        "_source_fitness_from_events_base",
        fake_base,
    )

    return expected


def test_runtime_corroboration_scan_skips_invalid_current_events(
    monkeypatch,
):
    import verboisy.core.source_assessment as module

    expected = _patch_runtime_fitness_base(monkeypatch)

    candidate, current = _corroboration_observation(
        snapshot_id="current",
        label="Agency A",
        host="agency-a.example",
    )

    payload = current["payload"]

    bad_claims = {
        "payload": {
            "version": payload["version"],
            "snapshot_id": "current",
            "candidate_key": (payload["candidate_key"]),
            "claims": [],
        }
    }

    wrong_candidate = {
        "payload": {
            **payload,
            "candidate_key": "wrong",
        }
    }

    malformed_payload = {
        "payload": "not-a-mapping",
    }

    result = module.source_fitness_from_events(
        [
            current,
            malformed_payload,
            wrong_candidate,
            bad_claims,
        ],
        snapshot_id="current",
        candidate=candidate,
    )

    assert result == expected


def test_runtime_corroboration_returns_base_when_no_current_event(
    monkeypatch,
):
    import verboisy.core.source_assessment as module

    expected = _patch_runtime_fitness_base(monkeypatch)

    candidate, _ = _corroboration_observation(
        snapshot_id="current",
        label="Agency A",
        host="agency-a.example",
    )

    result = module.source_fitness_from_events(
        [],
        snapshot_id="current",
        candidate=candidate,
    )

    assert result == expected


def test_runtime_corroboration_skips_ungrounded_current_claim(
    monkeypatch,
):
    import verboisy.core.source_assessment as module

    expected = _patch_runtime_fitness_base(monkeypatch)

    candidate, current = _corroboration_observation(
        snapshot_id="current",
        label="Agency A",
        host="agency-a.example",
    )

    current["payload"]["claims"]["/population"]["grounded"] = False

    result = module.source_fitness_from_events(
        [current],
        snapshot_id="current",
        candidate=candidate,
    )

    assert result == expected


def test_runtime_corroboration_skips_current_claim_without_origin(
    monkeypatch,
):
    import verboisy.core.source_assessment as module

    expected = _patch_runtime_fitness_base(monkeypatch)

    candidate, current = _corroboration_observation(
        snapshot_id="current",
        label="Agency A",
        host="agency-a.example",
    )

    current["payload"]["claims"]["/population"]["provenance_identity"] = None

    result = module.source_fitness_from_events(
        [current],
        snapshot_id="current",
        candidate=candidate,
    )

    assert result == expected


def test_runtime_corroboration_skips_invalid_observations(
    monkeypatch,
):
    from copy import deepcopy

    import verboisy.core.source_assessment as module

    _patch_runtime_fitness_base(monkeypatch)

    candidate, current = _corroboration_observation(
        snapshot_id="current",
        label="Agency A",
        host="agency-a.example",
    )

    payload = current["payload"]

    wrong_entity = {
        "payload": {
            **payload,
            "entity_key": "different-entity",
        }
    }

    bad_claims = {
        "payload": {
            "version": payload["version"],
            "entity_key": payload["entity_key"],
            "claims": [],
        }
    }

    no_origin = {
        "payload": deepcopy(payload),
    }

    no_origin["payload"]["snapshot_id"] = "other"

    no_origin["payload"]["claims"]["/population"]["provenance_identity"] = None

    result = module.source_fitness_from_events(
        [
            wrong_entity,
            bad_claims,
            no_origin,
            current,
        ],
        snapshot_id="current",
        candidate=candidate,
    )

    assert result is not None
    assert result["/population"].corroboration == 0


@pytest.mark.parametrize(
    "temporal_class",
    [
        "slow_changing",
        "mutable",
        "event",
        "time_series",
        "unknown",
    ],
)
def test_missing_year_cannot_corroborate_time_sensitive_claim(
    temporal_class,
):
    from verboisy.core.fitness import (
        ClaimFitness,
        FieldSemantics,
    )
    from verboisy.core.source_assessment import (
        _corroboration_period_available,
    )

    fitness = ClaimFitness(
        pointer="/value",
        authority="general",
        reference_year=None,
    )

    semantics = {
        "/value": FieldSemantics(
            pointer="/value",
            temporal_class=temporal_class,
        )
    }

    assert not _corroboration_period_available(
        "/value",
        fitness,
        semantics,
    )


def test_static_claim_can_corroborate_without_year():
    from verboisy.core.fitness import (
        ClaimFitness,
        FieldSemantics,
    )
    from verboisy.core.source_assessment import (
        _corroboration_period_available,
    )

    fitness = ClaimFitness(
        pointer="/value",
        authority="general",
        reference_year=None,
    )

    semantics = {
        "/value": FieldSemantics(
            pointer="/value",
            temporal_class="static",
        )
    }

    assert _corroboration_period_available(
        "/value",
        fitness,
        semantics,
    )


def test_explicit_year_allows_temporal_corroboration():
    from verboisy.core.fitness import (
        ClaimFitness,
        FieldSemantics,
    )
    from verboisy.core.source_assessment import (
        _corroboration_period_available,
    )

    fitness = ClaimFitness(
        pointer="/value",
        authority="general",
        reference_year=2025,
    )

    semantics = {
        "/value": FieldSemantics(
            pointer="/value",
            temporal_class="mutable",
        )
    }

    assert _corroboration_period_available(
        "/value",
        fitness,
        semantics,
    )


def test_legacy_corroboration_without_semantics_is_preserved():
    from verboisy.core.fitness import ClaimFitness
    from verboisy.core.source_assessment import (
        _corroboration_period_available,
    )

    fitness = ClaimFitness(
        pointer="/value",
        authority="general",
        reference_year=None,
    )

    assert _corroboration_period_available(
        "/value",
        fitness,
        None,
    )


@pytest.mark.parametrize(
    "existing_corroboration",
    [
        0,
        2,
    ],
)
def test_missing_period_clears_temporal_corroboration(
    monkeypatch,
    existing_corroboration,
):
    from verboisy.core.fitness import (
        ClaimFitness,
        FieldSemantics,
    )
    from verboisy.core.source_assessment import (
        SOURCE_FITNESS_EVENT_VERSION,
        source_fitness_candidate_key,
        source_fitness_from_events,
    )
    from verboisy.evidence.models import Candidate

    candidate = Candidate(
        scope="entity",
        record={
            "value": 10,
        },
        evidence={},
    )

    fitness = ClaimFitness(
        pointer="/value",
        authority="general",
        reference_year=None,
        corroboration=existing_corroboration,
    )

    monkeypatch.setattr(
        "verboisy.core.source_assessment." "_source_fitness_from_events_base",
        lambda *_args, **_kwargs: {
            "/value": fitness,
        },
    )

    events = [
        {
            "kind": "source_fitness",
            "payload": {
                "version": SOURCE_FITNESS_EVENT_VERSION,
                "snapshot_id": "snapshot-1",
                "candidate_key": (source_fitness_candidate_key(candidate)),
                "entity_key": "entity-1",
                "claims": {},
            },
        }
    ]

    result = source_fitness_from_events(
        events,
        snapshot_id="snapshot-1",
        candidate=candidate,
        field_semantics={
            "/value": FieldSemantics(
                pointer="/value",
                temporal_class="mutable",
            ),
        },
    )

    assert result is not None
    assert result["/value"].corroboration == 0


def _comparability_candidate():
    from verboisy.evidence.models import Candidate

    return Candidate(
        scope="entity",
        record={
            "population": 100,
        },
        evidence={},
        temporal_evidence={},
    )


def _comparability_page(
    *,
    scope="entity",
):
    from verboisy.evidence.models import (
        Snapshot,
        Source,
    )

    source = Source(
        id="metadata",
        kind="link",
        text=(
            "Population unit: thousands of persons. "
            "Definition: usual resident population. "
            "Method: annual demographic estimate."
        ),
        scope=scope,
        href="https://example.test/metadata",
    )

    return Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T12:00:00+00:00",
        content_hash="hash",
        sources=[
            source,
        ],
        truncated=False,
    )


def test_grounded_comparability_metadata_is_persisted():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
        source_fitness_event,
    )

    candidate = _comparability_candidate()
    page = _comparability_page()

    response = SourceAssessmentResponse(
        assessments=[
            ClaimSourceAssessment(
                pointer="/population",
                unit=ComparabilityDescriptor(
                    label="thousands of persons",
                    citation=AssessmentCitation(
                        source="metadata",
                        quote=("Population unit: " "thousands of persons."),
                    ),
                ),
                definition=ComparabilityDescriptor(
                    label=("usual resident population"),
                    citation=AssessmentCitation(
                        source="metadata",
                        quote=("Definition: usual resident " "population."),
                    ),
                ),
                methodology_identity=(
                    ComparabilityDescriptor(
                        label=("annual demographic estimate"),
                        citation=AssessmentCitation(
                            source="metadata",
                            quote=("Method: annual " "demographic estimate."),
                        ),
                    )
                ),
            )
        ]
    )

    grounded = ground_source_assessments(
        candidate,
        page,
        response,
    )

    comparability = grounded["/population"].comparability

    assert comparability is not None

    assert comparability.unit is not None
    assert comparability.unit.label == ("thousands of persons")

    assert comparability.definition is not None
    assert comparability.definition.label == ("usual resident population")

    assert comparability.methodology_identity is not None
    assert comparability.methodology_identity.label == "annual demographic estimate"

    event = source_fitness_event(
        page,
        candidate,
        grounded,
        cache_key="cache",
        cache_hit=False,
    )

    claim = event["claims"]["/population"]

    assert claim["comparability"] == {
        "unit": {
            "label": "thousands of persons",
            "source": "metadata",
            "quote": ("Population unit: " "thousands of persons."),
        },
        "definition": {
            "label": ("usual resident population"),
            "source": "metadata",
            "quote": ("Definition: usual resident " "population."),
        },
        "methodology_identity": {
            "label": ("annual demographic estimate"),
            "source": "metadata",
            "quote": ("Method: annual demographic " "estimate."),
        },
    }


def test_comparability_descriptor_must_be_literal():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _comparability_candidate(),
        _comparability_page(),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                    unit=ComparabilityDescriptor(
                        # Plausible paraphrase, but not
                        # literally observed.
                        label="people in thousands",
                        citation=AssessmentCitation(
                            source="metadata",
                            quote=("Population unit: " "thousands of persons."),
                        ),
                    ),
                )
            ]
        ),
    )

    assert result["/population"].comparability is None


def test_comparability_descriptor_requires_grounded_quote():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _comparability_candidate(),
        _comparability_page(),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                    unit=ComparabilityDescriptor(
                        label="persons",
                        citation=AssessmentCitation(
                            source="metadata",
                            quote=("Population is measured " "in persons."),
                        ),
                    ),
                )
            ]
        ),
    )

    assert result["/population"].comparability is None


def test_comparability_descriptor_respects_candidate_scope():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _comparability_candidate(),
        _comparability_page(
            scope="other-entity",
        ),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                    unit=ComparabilityDescriptor(
                        label="thousands of persons",
                        citation=AssessmentCitation(
                            source="metadata",
                            quote=("Population unit: " "thousands of persons."),
                        ),
                    ),
                )
            ]
        ),
    )

    assert result["/population"].comparability is None


def test_missing_comparability_source_is_ignored():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _comparability_candidate(),
        _comparability_page(),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                    unit=ComparabilityDescriptor(
                        label="thousands of persons",
                        citation=AssessmentCitation(
                            source="missing",
                            quote=("Population unit: " "thousands of persons."),
                        ),
                    ),
                )
            ]
        ),
    )

    assert result["/population"].comparability is None


def test_no_comparability_preserves_legacy_claim_event_shape():
    from verboisy.core.source_assessment import (
        ClaimSourceAssessment,
        SourceAssessmentResponse,
        ground_source_assessments,
    )

    result = ground_source_assessments(
        _comparability_candidate(),
        _comparability_page(),
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                )
            ]
        ),
    )

    event = result["/population"].as_event()

    assert "comparability" not in event


def test_empty_comparability_does_not_change_event_shape():
    from verboisy.core.fitness import ClaimFitness
    from verboisy.core.source_assessment import (
        GroundedClaimAssessment,
        GroundedClaimComparability,
    )

    assessment = GroundedClaimAssessment(
        pointer="/population",
        fitness=ClaimFitness(
            pointer="/population",
        ),
        grounded=True,
        reason=None,
        citation_sources=(),
        comparability=GroundedClaimComparability(),
    )

    event = assessment.as_event()

    assert "comparability" not in event


def _unit_comparability_event():
    from verboisy.core.source_assessment import (
        AssessmentCitation,
        ClaimSourceAssessment,
        ComparabilityDescriptor,
        SourceAssessmentResponse,
        ground_source_assessments,
        source_fitness_event,
    )

    candidate = _comparability_candidate()
    page = _comparability_page()

    grounded = ground_source_assessments(
        candidate,
        page,
        SourceAssessmentResponse(
            assessments=[
                ClaimSourceAssessment(
                    pointer="/population",
                    unit=ComparabilityDescriptor(
                        label="thousands of persons",
                        citation=AssessmentCitation(
                            source="metadata",
                            quote=("Population unit: " "thousands of persons."),
                        ),
                    ),
                )
            ]
        ),
    )

    event = source_fitness_event(
        page,
        candidate,
        grounded,
        cache_key="cache",
        cache_hit=False,
    )

    return candidate, page, event


def test_claim_comparability_is_reconstructed_from_event():
    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    result = claim_comparability_from_events(
        [
            {
                "payload": event,
            }
        ],
        snapshot=page,
        candidate=candidate,
    )

    assert set(result) == {
        "/population",
    }

    unit = result["/population"].unit

    assert unit is not None
    assert unit.label == ("thousands of persons")
    assert unit.source == "metadata"


def test_claim_comparability_rejects_tampered_quote():
    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    event["claims"]["/population"]["comparability"]["unit"]["quote"] = (
        "Population unit: millions of persons."
    )

    result = claim_comparability_from_events(
        [
            {
                "payload": event,
            }
        ],
        snapshot=page,
        candidate=candidate,
    )

    assert result == {}


def test_claim_comparability_ignores_wrong_snapshot():
    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    event["snapshot_id"] = "other"

    assert (
        claim_comparability_from_events(
            [
                {
                    "payload": event,
                }
            ],
            snapshot=page,
            candidate=candidate,
        )
        == {}
    )


def test_claim_comparability_ignores_legacy_claim():
    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    del event["claims"]["/population"]["comparability"]

    assert (
        claim_comparability_from_events(
            [
                {
                    "payload": event,
                }
            ],
            snapshot=page,
            candidate=candidate,
        )
        == {}
    )


def test_claim_comparability_ignores_malformed_descriptor():
    from copy import deepcopy

    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()
    event = deepcopy(event)

    event["claims"]["/population"]["comparability"]["unit"] = {
        "label": "",
        "source": "metadata",
        "quote": ("Population unit: " "thousands of persons."),
    }

    assert (
        claim_comparability_from_events(
            [{"payload": event}],
            snapshot=page,
            candidate=candidate,
        )
        == {}
    )


def test_claim_comparability_skips_non_dict_event_payload():
    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    result = claim_comparability_from_events(
        [
            {"payload": event},
            {"payload": "invalid"},
        ],
        snapshot=page,
        candidate=candidate,
    )

    assert result["/population"].unit is not None


def test_claim_comparability_skips_event_with_invalid_claims():
    from copy import deepcopy

    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()

    invalid = deepcopy(event)
    invalid["claims"] = "invalid"

    result = claim_comparability_from_events(
        [
            {"payload": event},
            {"payload": invalid},
        ],
        snapshot=page,
        candidate=candidate,
    )

    assert result["/population"].unit is not None


@pytest.mark.parametrize(
    "claims",
    [
        {
            123: {},
        },
        {
            "/population": "invalid",
        },
    ],
)
def test_claim_comparability_skips_invalid_claim_entries(
    claims,
):
    from copy import deepcopy

    from verboisy.core.source_assessment import (
        claim_comparability_from_events,
    )

    candidate, page, event = _unit_comparability_event()
    event = deepcopy(event)
    event["claims"] = claims

    assert (
        claim_comparability_from_events(
            [{"payload": event}],
            snapshot=page,
            candidate=candidate,
        )
        == {}
    )
