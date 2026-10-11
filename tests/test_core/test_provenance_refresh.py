# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reference-period refresh must retain temporal and source-quality safeguards."""

from dataclasses import replace

import pytest
from verboisy.core.fitness import (
    ClaimFitness,
    FieldSemantics,
    compare_candidate_fitness,
    compare_candidate_with_source_fitness,
)
from verboisy.core.planner import TemporalIntent
from verboisy.evidence.models import Candidate, TemporalProof

SEMANTICS = {
    "/population": FieldSemantics(
        pointer="/population",
        temporal_class="mutable",
        reference_period="required",
        temporal_intent=TemporalIntent(mode="latest"),
    )
}


def observation(year, value=2000):
    return Candidate(
        scope="entity",
        record={"name": "Alba", "population": value},
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source=f"reference-{year}",
                quote=f"Reference year: {year}",
                reference_year=year,
            )
        }
        if year
        else {},
    )


@pytest.mark.parametrize(
    ("old_year", "new_year", "expected"),
    [
        (2024, 2025, "new"),
        (2025, 2024, "old"),
        (2025, 2025, "same"),
        (None, 2025, "same"),
        (2025, None, "same"),
    ],
)
def test_equal_values_compare_reference_years(old_year, new_year, expected):
    result = compare_candidate_fitness(observation(old_year), observation(new_year), SEMANTICS)
    assert result.preference == expected
    assert result.changed_fields == ()
    assert result.newer_fields == (("/population",) if expected == "new" else ())
    assert result.older_fields == (("/population",) if expected == "old" else ())


@pytest.mark.parametrize("intent", [None, TemporalIntent(mode="latest")])
def test_equal_values_with_no_period_change_stay_same(intent):
    semantics = {"/population": replace(SEMANTICS["/population"], temporal_intent=intent)}
    assert (
        compare_candidate_fitness(observation(2025), observation(2025), semantics).preference
        == "same"
    )


@pytest.mark.parametrize("quality", ["equal", "worse", "missing", "unknown"])
def test_equal_value_refresh_is_subject_to_quality_checks(quality):
    old = ClaimFitness(pointer="/population", authority="responsible")
    new = old if quality == "equal" else replace(old, authority="general")
    new_map = {"/population": new}
    if quality == "missing":
        new_map = {}
    elif quality == "unknown":
        new_map = {"/population": ClaimFitness(pointer="/population")}
    result = compare_candidate_with_source_fitness(
        observation(2024), observation(2025), SEMANTICS, {"/population": old}, new_map
    )
    assert result.temporal_preference == "new"
    assert result.preference == ("new" if quality == "equal" else "old")
    assert result.changed_fields == ()


def test_mixed_period_directions_do_not_replace_whole_candidate():
    old = observation(2024)
    new = observation(2025)
    for candidate, year in [(old, 2025), (new, 2024)]:
        candidate.record["area"] = 100
        candidate.temporal_evidence["/area"] = TemporalProof(
            source="area-year", quote=str(year), reference_year=year
        )
    semantics = {**SEMANTICS, "/area": replace(SEMANTICS["/population"], pointer="/area")}
    assert compare_candidate_fitness(old, new, semantics).preference == "conflict"
    assert (
        compare_candidate_with_source_fitness(old, new, semantics, {}, {}).preference == "conflict"
    )


@pytest.mark.parametrize("year", [2023, 2025])
def test_same_period_value_conflict_cannot_hide_other_period_changes(year):
    old = observation(2024, 100)
    new = observation(2024, 200)
    for candidate, reference_year in [(old, 2024), (new, year)]:
        candidate.record["area"] = 100
        candidate.temporal_evidence["/area"] = TemporalProof(
            source="area-year", quote=str(reference_year), reference_year=reference_year
        )
    semantics = {**SEMANTICS, "/area": replace(SEMANTICS["/population"], pointer="/area")}
    old_quality = {"/population": ClaimFitness(pointer="/population", authority="general")}
    new_quality = {"/population": ClaimFitness(pointer="/population", authority="responsible")}
    assert (
        compare_candidate_with_source_fitness(
            old, new, semantics, old_quality, new_quality
        ).preference
        == "conflict"
    )
