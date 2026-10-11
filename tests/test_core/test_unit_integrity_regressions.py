# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Regression contracts for exact scaling and complete unit grounding."""

import pytest
from verboisy.core.source_assessment import (
    SourceAssessmentResponse,
    claim_comparability_from_events,
    ground_source_assessments,
    source_fitness_event,
)
from verboisy.core.units import CanonicalUnit, canonical_unit, normalize_unit_value
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source


def test_large_integer_scaling_is_exact():
    unit = canonical_unit("thousands of persons")
    assert unit is not None
    original = 10**30 + 1

    assert normalize_unit_value(original, unit) == original * 1000


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_not_normalized(value):
    unit = canonical_unit("thousands of persons")
    assert unit is not None

    assert normalize_unit_value(value, unit) is None


def assessment_fixture(observed_label, proposed_label, quote=None):
    observed = f"Value unit: {observed_label}."
    quote = observed if quote is None else quote
    candidate = Candidate(
        scope="entity",
        record={"value": 2},
        evidence={"/value": Proof(source="value", quote="2", transform="integer")},
    )
    page = Snapshot(
        id="unit-fixture",
        url="https://example.test/measurements",
        fetched_at="2026-10-03T00:00:00+00:00",
        content_hash="fixture",
        truncated=False,
        sources=[
            Source(id="value", kind="text", text="2", scope="entity"),
            Source(id="metadata", kind="text", text=observed, scope="entity"),
        ],
    )
    response = SourceAssessmentResponse.model_validate(
        {
            "assessments": [
                {
                    "pointer": "/value",
                    "unit": {
                        "label": proposed_label,
                        "citation": {"source": "metadata", "quote": quote},
                    },
                }
            ]
        }
    )
    return candidate, page, response


def assessed_unit(observed_label, proposed_label, quote=None):
    candidate, page, response = assessment_fixture(observed_label, proposed_label, quote)
    claim = ground_source_assessments(candidate, page, response)["/value"]
    return None if claim.comparability is None else claim.comparability.unit


@pytest.mark.parametrize("label", ["persons", "thousands of persons", "g", "kg"])
def test_complete_observed_unit_remains_grounded(label):
    unit = assessed_unit(label, label)

    assert unit is not None
    assert unit.label == label


@pytest.mark.parametrize(
    ("observed", "proposed"),
    [("thousands of persons", "persons"), ("kg", "g")],
)
def test_partial_unit_label_cannot_change_the_scale(observed, proposed):
    assert assessed_unit(observed, proposed) is None


@pytest.mark.parametrize(
    ("observed", "proposed"),
    [
        ("thousands of persons", "persons"),
        ("kg", "g"),
        ("millions of kg", "kg"),
        ("Thousands Of Persons", "Persons"),
    ],
)
def test_shortened_quote_cannot_hide_enclosing_scale(observed, proposed):
    assert assessed_unit(observed, proposed, quote=proposed) is None


@pytest.mark.parametrize("label", ["persons", "thousands of persons", "kg", "widgets"])
def test_complete_unit_metadata_survives_event_replay(label):
    candidate, page, response = assessment_fixture(label, label)
    claims = ground_source_assessments(candidate, page, response)
    event = source_fitness_event(page, candidate, claims, cache_key="fixture", cache_hit=False)

    restored = claim_comparability_from_events(
        [{"payload": event}], snapshot=page, candidate=candidate
    )

    assert restored["/value"].unit.label == label


def test_legacy_event_with_truncated_unit_is_regrounded():
    candidate, page, response = assessment_fixture("thousands of persons", "thousands of persons")
    claims = ground_source_assessments(candidate, page, response)
    event = source_fitness_event(page, candidate, claims, cache_key="fixture", cache_hit=False)
    event["claims"]["/value"]["comparability"]["unit"].update(label="persons", quote="persons")

    restored = claim_comparability_from_events(
        [{"payload": event}], snapshot=page, candidate=candidate
    )

    assert restored == {}


def test_unit_rejection_preserves_other_grounded_metadata():
    candidate, page, response = assessment_fixture("thousands of persons", "persons")
    raw = response.model_dump()
    raw["assessments"][0]["definition"] = raw["assessments"][0]["unit"]
    response = SourceAssessmentResponse.model_validate(raw)

    claims = ground_source_assessments(candidate, page, response)
    comparability = claims["/value"].comparability
    assert comparability.unit is None
    assert comparability.definition.label == "persons"


def test_fractional_overflow_remains_unresolved():
    unit = CanonicalUnit("count", "person", 10**400 + 1)

    assert normalize_unit_value(0.5, unit) is None


def test_decimal_scaling_is_independent_of_decimal_context():
    from decimal import localcontext

    unit = canonical_unit("thousands of persons")
    with localcontext() as context:
        context.prec = 2
        assert normalize_unit_value(1.2345, unit) == 1234.5
