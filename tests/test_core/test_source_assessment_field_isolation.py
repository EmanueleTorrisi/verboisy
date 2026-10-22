# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Keep each field's citations, classifications and reference period independent."""

from copy import deepcopy

import pytest
from verboisy.core.source_assessment import (
    AssessmentCitation,
    ClaimSourceAssessment,
    SourceAssessmentResponse,
    ground_source_assessments,
    source_fitness_event,
    source_fitness_from_events,
)
from verboisy.evidence.models import Candidate, Snapshot, Source, TemporalProof


@pytest.fixture
def release_assessments():
    page = Snapshot(
        id="release-snapshot",
        url="https://example.test/release/",
        fetched_at="2026-10-22T00:00:00+00:00",
        content_hash="fixture",
        truncated=False,
        sources=[
            Source(id="e27", kind="text", text="Python 3.13.0", scope="release"),
            Source(id="e31", kind="text", text="Oct. 7, 2024", scope="release"),
        ],
    )
    candidate = Candidate(
        scope="release",
        record={"version": "3.13.0", "release_date": "Oct. 7, 2024"},
        evidence={},
        temporal_evidence={
            "/release_date": TemporalProof(source="e31", quote="Oct. 7, 2024", reference_year=2024)
        },
    )
    response = SourceAssessmentResponse(
        assessments=[
            ClaimSourceAssessment(
                pointer="/version",
                authority="general",
                directness="primary",
                methodology="absent",
                provenance="opaque",
                citations=[AssessmentCitation(source="e27", quote="3.13.0")],
            ),
            ClaimSourceAssessment(
                pointer="/release_date",
                authority="responsible",
                directness="secondary",
                methodology="explicit",
                provenance="traceable",
                citations=[AssessmentCitation(source="e31", quote="Oct. 7, 2024")],
            ),
        ]
    )
    return candidate, page, response


@pytest.mark.parametrize("reverse", [False, True])
def test_multi_field_assessments_keep_their_own_metadata_and_roundtrip(
    release_assessments, reverse
):
    candidate, page, response = release_assessments
    if reverse:
        response.assessments.reverse()
    originals = deepcopy((candidate, page, response))
    claims = ground_source_assessments(candidate, page, response)
    expected_years = {"/version": None, "/release_date": 2024}
    expected_sources = {"/version": ("e27",), "/release_date": ("e31",)}
    for assessment in response.assessments:
        pointer = assessment.pointer
        claim = claims[pointer]
        assert claim.pointer == claim.fitness.pointer == pointer
        assert claim.grounded is True
        assert claim.reason is None
        assert claim.citation_sources == expected_sources[pointer]
        assert claim.fitness.reference_year == expected_years[pointer]
        for attribute in ("authority", "directness", "methodology", "provenance"):
            assert getattr(claim.fitness, attribute) == getattr(assessment, attribute)
    event = source_fitness_event(
        page, candidate, claims, cache_key="fixture", cache_hit=False, identity_fields=("/version",)
    )
    restored = source_fitness_from_events(
        [{"kind": "source_fitness", "payload": event}], snapshot_id=page.id, candidate=candidate
    )
    assert restored == {pointer: claim.fitness for pointer, claim in claims.items()}
    assert (candidate, page, response) == originals


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("bad_pointer", ["/version", "/release_date"])
def test_one_unobserved_citation_cannot_borrow_another_fields_evidence(
    release_assessments, reverse, bad_pointer
):
    candidate, page, response = release_assessments
    for assessment in response.assessments:
        if assessment.pointer == bad_pointer:
            assessment.citations[0].quote = "Unobserved claim"
    if reverse:
        response.assessments.reverse()
    claims = ground_source_assessments(candidate, page, response)
    bad = claims[bad_pointer]
    assert bad.grounded is False
    assert bad.reason == "ungrounded_source_assessment"
    assert bad.citation_sources == ()
    assert bad.fitness.pointer == bad_pointer
    assert bad.fitness.authority == "unknown"
    good_pointer = "/release_date" if bad_pointer == "/version" else "/version"
    good = claims[good_pointer]
    assert good.grounded is True
    assert good.fitness.pointer == good_pointer
    assert good.citation_sources == (("e31",) if good_pointer == "/release_date" else ("e27",))


@pytest.mark.parametrize("reverse", [False, True])
def test_uninformative_field_does_not_erase_another_fields_grounded_assessment(
    release_assessments, reverse
):
    candidate, page, response = release_assessments
    response.assessments[1] = ClaimSourceAssessment(pointer="/release_date")
    if reverse:
        response.assessments.reverse()
    claims = ground_source_assessments(candidate, page, response)
    assert claims["/version"].grounded is True
    assert claims["/version"].citation_sources == ("e27",)
    assert claims["/version"].fitness.authority == "general"
    assert claims["/version"].fitness.reference_year is None
    assert claims["/release_date"].grounded is True
    assert claims["/release_date"].citation_sources == ()
    assert claims["/release_date"].fitness.authority == "unknown"
    assert claims["/release_date"].fitness.reference_year == 2024
