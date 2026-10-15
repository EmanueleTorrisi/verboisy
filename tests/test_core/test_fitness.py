# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from dataclasses import replace

import pytest
from verboisy.core.fitness import (
    FieldSemantics,
    build_field_semantics,
    is_mutable_pointer,
    mutable_field_patterns,
    pointer_pattern,
    requires_temporal_evidence,
    scalar_field_schemas,
    semantics_for_pointer,
    temporal_errors,
)
from verboisy.core.planner import TemporalIntent
from verboisy.evidence.models import (
    Candidate,
    Snapshot,
    Source,
    TemporalProof,
)

BASE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
            },
            "population": {
                "type": "integer",
            },
        },
    },
}


EXPLICIT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-verboisy-temporal-class": "static",
            },
            "population": {
                "type": "integer",
                "x-verboisy-temporal-class": "mutable",
                "x-verboisy-reference-period": "required",
                "x-verboisy-comparable-across-rows": True,
            },
            "area": {
                "type": "number",
                "x-verboisy-temporal-class": "slow_changing",
                "x-verboisy-reference-period": "preferred",
                "x-verboisy-definition-sensitive": True,
                "x-verboisy-unit-sensitive": True,
            },
        },
    },
}


def page(*sources: Source) -> Snapshot:
    return Snapshot(
        id="snapshot",
        url="https://data.test/",
        fetched_at="2026-09-30T00:00:00Z",
        content_hash="hash",
        sources=list(sources),
        truncated=False,
    )


def candidate(
    *,
    temporal_evidence=None,
) -> Candidate:
    return Candidate(
        scope="s1",
        record={
            "name": "Canada",
            "population": 41_000_000,
            "area": 9_984_670,
        },
        evidence={},
        temporal_evidence=(temporal_evidence or {}),
    )


def test_plain_schema_does_not_guess_field_meaning():
    semantics = build_field_semantics(BASE_SCHEMA)

    assert semantics["/population"] == FieldSemantics(pointer="/population")
    assert mutable_field_patterns(BASE_SCHEMA) == []
    assert not is_mutable_pointer(
        BASE_SCHEMA,
        "/population",
    )


def test_explicit_schema_semantics_are_preserved():
    semantics = build_field_semantics(EXPLICIT_SCHEMA)

    population = semantics["/population"]
    area = semantics["/area"]

    assert population.temporal_class == "mutable"
    assert population.reference_period == "required"
    assert population.comparable_across_rows
    assert population.confidence == 1.0
    assert population.basis == "explicit"

    assert area.temporal_class == "slow_changing"
    assert area.reference_period == "preferred"
    assert area.definition_sensitive
    assert area.unit_sensitive

    assert mutable_field_patterns(EXPLICIT_SCHEMA) == [
        "/area",
        "/population",
    ]


def test_invalid_explicit_semantics_fail_closed():
    schema = {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "x-verboisy-temporal-class": "magic",
                "x-verboisy-reference-period": "sometimes",
            }
        },
    }

    semantics = build_field_semantics(schema)["/value"]

    assert semantics.temporal_class == "unknown"
    assert semantics.reference_period == "none"
    assert semantics.basis == "explicit"
    assert semantics.confidence == 1.0


def test_nested_arrays_use_wildcard_pointer_patterns():
    schema = {
        "type": "object",
        "properties": {
            "history": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "number",
                            "x-verboisy-temporal-class": "time_series",
                        }
                    },
                },
            },
            "a/b~c": {
                "type": "string",
            },
            "ignored": "not-a-schema",
        },
    }

    fields = scalar_field_schemas(schema)

    assert set(fields) == {
        "/history/*/value",
        "/a~1b~0c",
    }

    semantics = build_field_semantics(schema)

    assert (
        semantics_for_pointer(
            semantics,
            "/history/12/value",
        ).temporal_class
        == "time_series"
    )

    assert pointer_pattern("/history/12/value") == "/history/*/value"


def test_semantics_lookup_can_miss_unknown_pointer():
    assert (
        semantics_for_pointer(
            build_field_semantics(BASE_SCHEMA),
            "/missing",
        )
        is None
    )


def test_temporal_requirement_depends_on_semantics_and_intent():
    required = FieldSemantics(
        pointer="/value",
        temporal_class="static",
        reference_period="required",
    )
    mutable = FieldSemantics(
        pointer="/value",
        temporal_class="mutable",
        reference_period="preferred",
    )
    static = FieldSemantics(
        pointer="/value",
        temporal_class="static",
    )

    assert requires_temporal_evidence(
        required,
        TemporalIntent(mode="latest"),
    )
    assert not requires_temporal_evidence(
        mutable,
        TemporalIntent(
            mode="year",
            start_year=2020,
            end_year=2020,
        ),
    )
    assert not requires_temporal_evidence(
        mutable,
        TemporalIntent(mode="latest"),
    )
    assert not requires_temporal_evidence(
        static,
        TemporalIntent(
            mode="range",
            start_year=1970,
            end_year=1979,
        ),
    )


def test_latest_requires_explicitly_required_temporal_evidence():
    errors = temporal_errors(
        candidate(),
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == ["/population:" "missing_temporal_evidence"]


def test_null_mutable_value_does_not_require_period():
    value = candidate()
    value.record["population"] = None

    errors = temporal_errors(
        value,
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == []


def test_latest_accepts_observed_page_level_year():
    proof = TemporalProof(
        source="year",
        quote="Population reference year 2025",
        reference_year=2025,
    )

    errors = temporal_errors(
        candidate(temporal_evidence={"/population": proof}),
        page(
            Source(
                id="year",
                kind="text",
                text=("Population reference " "year 2025"),
                scope="page",
            )
        ),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == []


def test_preferred_temporal_proof_is_optional_but_validated():
    errors = temporal_errors(
        candidate(),
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert "/area:missing_temporal_evidence" not in errors


def test_temporal_source_must_exist():
    proof = TemporalProof(
        source="missing",
        quote="2025",
        reference_year=2025,
    )

    errors = temporal_errors(
        candidate(temporal_evidence={"/population": proof}),
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == ["/population:" "temporal_source_outside_scope"]


def test_temporal_source_must_be_entity_or_page_scope():
    proof = TemporalProof(
        source="year",
        quote="Population 2025",
        reference_year=2025,
    )

    errors = temporal_errors(
        candidate(temporal_evidence={"/population": proof}),
        page(
            Source(
                id="year",
                kind="text",
                text="Population 2025",
                scope="s2",
            )
        ),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == ["/population:" "temporal_source_outside_scope"]


def test_temporal_quote_must_be_nonempty_observed_and_contain_year():
    source = Source(
        id="year",
        kind="text",
        text="Population estimate for 2025",
        scope="page",
    )

    for quote in (
        "",
        "Population estimate",
        "Population estimate for 2024",
    ):
        errors = temporal_errors(
            candidate(
                temporal_evidence={
                    "/population": TemporalProof(
                        source="year",
                        quote=quote,
                        reference_year=2025,
                    )
                }
            ),
            page(source),
            EXPLICIT_SCHEMA,
            TemporalIntent(mode="latest"),
            current_year=2026,
        )

        assert errors == ["/population:" "temporal_quote_not_observed"]


def test_latest_rejects_future_projection():
    errors = temporal_errors(
        candidate(
            temporal_evidence={
                "/population": TemporalProof(
                    source="year",
                    quote="Projection 2030",
                    reference_year=2030,
                )
            }
        ),
        page(
            Source(
                id="year",
                kind="text",
                text="Projection 2030",
                scope="page",
            )
        ),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == ["/population:" "future_temporal_value"]


def test_explicit_year_must_match():
    errors = temporal_errors(
        candidate(
            temporal_evidence={
                "/population": TemporalProof(
                    source="year",
                    quote="Population 2024",
                    reference_year=2024,
                )
            }
        ),
        page(
            Source(
                id="year",
                kind="text",
                text="Population 2024",
                scope="page",
            )
        ),
        EXPLICIT_SCHEMA,
        TemporalIntent(
            mode="year",
            start_year=2020,
            end_year=2020,
        ),
        current_year=2026,
    )

    assert errors == ["/population:" "temporal_mismatch"]


def test_explicit_range_accepts_matching_year():
    semantics = build_field_semantics(EXPLICIT_SCHEMA)

    errors = temporal_errors(
        candidate(
            temporal_evidence={
                "/population": TemporalProof(
                    source="year",
                    quote="Population 1975",
                    reference_year=1975,
                )
            }
        ),
        page(
            Source(
                id="year",
                kind="text",
                text="Population 1975",
                scope="page",
            )
        ),
        EXPLICIT_SCHEMA,
        TemporalIntent(
            mode="range",
            start_year=1970,
            end_year=1979,
        ),
        current_year=2026,
        field_semantics=semantics,
    )

    assert errors == []


def test_explicit_range_rejects_missing_bounds_and_outside_year():
    proof = TemporalProof(
        source="year",
        quote="Population 1975",
        reference_year=1975,
    )
    value = candidate(temporal_evidence={"/population": proof})
    source = page(
        Source(
            id="year",
            kind="text",
            text="Population 1975",
            scope="page",
        )
    )

    for intent in (
        TemporalIntent(
            mode="range",
            start_year=None,
            end_year=1979,
        ),
        TemporalIntent(
            mode="range",
            start_year=1980,
            end_year=1989,
        ),
    ):
        assert temporal_errors(
            value,
            source,
            EXPLICIT_SCHEMA,
            intent,
            current_year=2026,
        ) == ["/population:" "temporal_mismatch"]


def test_unknown_temporal_pointer_is_rejected():
    errors = temporal_errors(
        candidate(
            temporal_evidence={
                "/missing": TemporalProof(
                    source="year",
                    quote="2025",
                    reference_year=2025,
                )
            }
        ),
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert errors == [
        "unknown_temporal_evidence_pointer",
        "/population:" "missing_temporal_evidence",
    ]


def test_field_semantics_serializes_for_events():
    semantics = FieldSemantics(
        pointer="/population",
        temporal_class="mutable",
        reference_period="required",
        definition_sensitive=False,
        unit_sensitive=False,
        comparable_across_rows=True,
        confidence=0.95,
        basis="model",
    )

    assert semantics.as_event() == {
        "pointer": "/population",
        "temporal_class": "mutable",
        "reference_period": "required",
        "temporal_intent": None,
        "definition_sensitive": False,
        "unit_sensitive": False,
        "methodology_sensitive": False,
        "comparable_across_rows": True,
        "confidence": 0.95,
        "basis": "model",
    }


def test_temporal_validation_ignores_field_without_semantics():
    errors = temporal_errors(
        candidate(),
        page(),
        EXPLICIT_SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
        field_semantics={},
    )

    assert errors == []


def _fitness_candidate(
    *,
    population=100,
    year=2024,
    name="Example",
):
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    temporal = {}

    if year is not None:
        temporal["/population"] = TemporalProof(
            source="e1",
            quote=f"Population {year}",
            reference_year=year,
        )

    return Candidate(
        scope="s1",
        record={
            "name": name,
            "population": population,
        },
        evidence={},
        temporal_evidence=temporal,
    )


def _latest_semantics():
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )

    return {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            reference_period="none",
            confidence=1.0,
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=1.0,
            basis="model",
        ),
    }


def test_candidate_comparison_identical_records_are_same():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    candidate = _fitness_candidate()

    result = compare_candidate_fitness(
        candidate,
        candidate,
        _latest_semantics(),
    )

    assert result.preference == "same"
    assert result.changed_fields == ()
    assert result.as_event()["preference"] == "same"


def test_candidate_comparison_prefers_newer_latest_fact():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        population=100,
        year=2022,
    )
    new = _fitness_candidate(
        population=110,
        year=2025,
    )

    result = compare_candidate_fitness(
        old,
        new,
        _latest_semantics(),
    )

    assert result.preference == "new"
    assert result.changed_fields == ("/population",)
    assert result.newer_fields == ("/population",)
    assert result.older_fields == ()
    assert result.unresolved_fields == ()


def test_candidate_comparison_prefers_existing_newer_fact():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        population=110,
        year=2025,
    )
    new = _fitness_candidate(
        population=100,
        year=2022,
    )

    result = compare_candidate_fitness(
        old,
        new,
        _latest_semantics(),
    )

    assert result.preference == "old"
    assert result.older_fields == ("/population",)


def test_candidate_comparison_same_year_disagreement_conflicts():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        population=100,
        year=2025,
    )
    new = _fitness_candidate(
        population=110,
        year=2025,
    )

    result = compare_candidate_fitness(
        old,
        new,
        _latest_semantics(),
    )

    assert result.preference == "conflict"
    assert result.unresolved_fields == ("/population",)


def test_candidate_comparison_missing_temporal_proof_conflicts():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        population=100,
        year=None,
    )
    new = _fitness_candidate(
        population=110,
        year=2025,
    )

    result = compare_candidate_fitness(
        old,
        new,
        _latest_semantics(),
    )

    assert result.preference == "conflict"
    assert result.unresolved_fields == ("/population",)


def test_candidate_comparison_static_disagreement_conflicts():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        name="Old name",
    )
    new = _fitness_candidate(
        name="New name",
    )

    result = compare_candidate_fitness(
        old,
        new,
        _latest_semantics(),
    )

    assert result.preference == "conflict"
    assert result.unresolved_fields == ("/name",)


def test_candidate_comparison_unknown_field_conflicts():
    from verboisy.core.fitness import (
        compare_candidate_fitness,
    )

    old = _fitness_candidate(
        population=100,
    )
    new = _fitness_candidate(
        population=110,
    )

    result = compare_candidate_fitness(
        old,
        new,
        {},
    )

    assert result.preference == "conflict"
    assert result.unresolved_fields == ("/population",)


def test_candidate_comparison_historical_field_does_not_use_freshness():
    from verboisy.core.fitness import (
        FieldSemantics,
        compare_candidate_fitness,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )

    semantics = _latest_semantics()
    semantics["/population"] = FieldSemantics(
        pointer="/population",
        temporal_class="mutable",
        reference_period="required",
        temporal_intent=TemporalIntent(
            mode="year",
            start_year=1975,
            end_year=1975,
        ),
        confidence=1.0,
        basis="model",
    )

    result = compare_candidate_fitness(
        _fitness_candidate(
            population=100,
            year=1974,
        ),
        _fitness_candidate(
            population=110,
            year=1975,
        ),
        semantics,
    )

    assert result.preference == "conflict"
    assert result.unresolved_fields == ("/population",)


def test_candidate_comparison_mixed_temporal_direction_conflicts():
    from verboisy.core.fitness import (
        FieldSemantics,
        compare_candidate_fitness,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    semantics = {
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            basis="model",
        ),
        "/employees": FieldSemantics(
            pointer="/employees",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            basis="model",
        ),
    }

    old = Candidate(
        scope="s1",
        record={
            "population": 100,
            "employees": 50,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e1",
                quote="2022",
                reference_year=2022,
            ),
            "/employees": TemporalProof(
                source="e2",
                quote="2025",
                reference_year=2025,
            ),
        },
    )

    new = Candidate(
        scope="s1",
        record={
            "population": 110,
            "employees": 40,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e3",
                quote="2025",
                reference_year=2025,
            ),
            "/employees": TemporalProof(
                source="e4",
                quote="2023",
                reference_year=2023,
            ),
        },
    )

    result = compare_candidate_fitness(
        old,
        new,
        semantics,
    )

    assert result.preference == "conflict"
    assert result.newer_fields == ("/population",)
    assert result.older_fields == ("/employees",)


def test_claim_fitness_equal_is_same():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    fitness = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=2,
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            fitness,
            fitness,
            prefer_latest=True,
        )
        == "same"
    )


def test_claim_fitness_newer_equal_quality_wins():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=1,
        reference_year=2023,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=1,
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "new"
    )


def test_claim_fitness_better_quality_same_year_wins():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="partial",
        provenance="attributed",
        corroboration=1,
        reference_year=2025,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=2,
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "new"
    )


def test_claim_fitness_freshness_quality_tradeoff_conflicts():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=2,
        reference_year=2024,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="absent",
        provenance="opaque",
        corroboration=0,
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "conflict"
    )


def test_claim_fitness_older_better_source_also_conflicts():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="partial",
        provenance="attributed",
        reference_year=2025,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        reference_year=2024,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "conflict"
    )


def test_claim_fitness_latest_year_ignored_for_historical_claim():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        reference_year=2020,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=False,
        )
        == "same"
    )


def test_claim_fitness_more_corroboration_can_dominate():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=1,
        reference_year=2025,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=3,
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "new"
    )


def test_claim_fitness_negative_corroboration_is_neutralized():
    from verboisy.core.fitness import (
        ClaimFitness,
        claim_fitness_vector,
    )

    vector = claim_fitness_vector(
        ClaimFitness(
            pointer="/value",
            corroboration=-5,
        ),
        prefer_latest=False,
    )

    assert vector[-1] == 0


def test_claim_fitness_missing_year_loses_when_otherwise_equal():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        reference_year=None,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        reference_year=2025,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "new"
    )


def test_claim_fitness_different_claims_cannot_be_compared():
    import pytest
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    with pytest.raises(
        ValueError,
        match="different claims",
    ):
        compare_claim_fitness(
            ClaimFitness(pointer="/population"),
            ClaimFitness(pointer="/revenue"),
            prefer_latest=True,
        )


def test_claim_fitness_as_event_serializes_all_fields():
    from verboisy.core.fitness import ClaimFitness

    fitness = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=2,
        reference_year=2025,
    )

    assert fitness.as_event() == {
        "pointer": "/population",
        "authority": "specialist",
        "directness": "primary",
        "methodology": "explicit",
        "provenance": "traceable",
        "corroboration": 2,
        "reference_year": 2025,
    }


def test_claim_fitness_existing_candidate_can_dominate():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_claim_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="explicit",
        provenance="traceable",
        corroboration=3,
        reference_year=2025,
    )
    new = ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="partial",
        provenance="attributed",
        corroboration=1,
        reference_year=2024,
    )

    assert (
        compare_claim_fitness(
            old,
            new,
            prefer_latest=True,
        )
        == "old"
    )


def _quality_candidate(
    value,
    year,
):
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    return Candidate(
        scope="page",
        record={
            "name": "Example",
            "population": value,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e1",
                quote=str(year),
                reference_year=year,
            )
        },
    )


def _latest_population_semantics():
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )

    return {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            reference_period="none",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
        ),
    }


def _strong_claim(year):
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
        reference_year=year,
    )


def _weak_claim(year):
    from verboisy.core.fitness import (
        ClaimFitness,
    )

    return ClaimFitness(
        pointer="/population",
        authority="general",
        directness="secondary",
        methodology="partial",
        provenance="attributed",
        corroboration=0,
        reference_year=year,
    )


def test_quality_signal_excludes_temporal_year_only():
    from verboisy.core.fitness import (
        ClaimFitness,
        claim_fitness_has_quality_signal,
    )

    assert not claim_fitness_has_quality_signal(
        ClaimFitness(
            pointer="/population",
            reference_year=2025,
        )
    )

    assert claim_fitness_has_quality_signal(_strong_claim(2025))


def test_newer_equal_quality_can_supersede():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2022,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_strong_claim(2022))},
        {"/population": (_strong_claim(2025))},
    )

    assert result.temporal_preference == "new"
    assert result.preference == "new"
    assert result.blocked_fields == ()
    assert result.missing_fields == ()
    assert result.source_preferences["/population"] == "same"


def test_newer_better_source_can_supersede():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2022,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_weak_claim(2022))},
        {"/population": (_strong_claim(2025))},
    )

    assert result.preference == "new"
    assert result.source_preferences["/population"] == "new"


def test_newer_weaker_source_does_not_supersede():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2024,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_strong_claim(2024))},
        {"/population": (_weak_claim(2025))},
    )

    assert result.temporal_preference == "new"
    assert result.preference == "old"
    assert result.blocked_fields == ("/population",)
    assert result.source_preferences["/population"] == "old"


def test_newer_quality_tradeoff_retains_incumbent():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_candidate_with_source_fitness,
    )

    old = ClaimFitness(
        pointer="/population",
        authority="responsible",
        directness="primary",
        methodology="partial",
        provenance="traceable",
        reference_year=2024,
    )

    new = ClaimFitness(
        pointer="/population",
        authority="specialist",
        directness="primary",
        methodology="explicit",
        provenance="attributed",
        reference_year=2025,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2024,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {
            "/population": old,
        },
        {
            "/population": new,
        },
    )

    assert result.preference == "old"
    assert result.blocked_fields == ("/population",)
    assert result.source_preferences["/population"] == "conflict"


def test_newer_without_source_fitness_does_not_supersede():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2024,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {},
        {},
    )

    assert result.preference == "old"
    assert result.missing_fields == ("/population",)


def test_newer_unknown_quality_does_not_supersede():
    from verboisy.core.fitness import (
        ClaimFitness,
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2024,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (ClaimFitness(pointer=("/population")))},
        {"/population": (ClaimFitness(pointer=("/population")))},
    )

    assert result.preference == "old"
    assert result.missing_fields == ("/population",)


def test_older_candidate_remains_old_even_with_better_source():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            110,
            2025,
        ),
        _quality_candidate(
            100,
            2024,
        ),
        _latest_population_semantics(),
        {"/population": (_weak_claim(2025))},
        {"/population": (_strong_claim(2024))},
    )

    assert result.temporal_preference == "old"
    assert result.preference == "old"
    assert result.source_preferences == {}


def test_same_year_stronger_new_source_resolves_conflict():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2025,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_weak_claim(2025))},
        {"/population": (_strong_claim(2025))},
    )

    assert result.temporal_preference == "conflict"
    assert result.preference == "new"
    assert result.source_preferences["/population"] == "new"


def test_same_year_stronger_old_source_keeps_incumbent():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2025,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_strong_claim(2025))},
        {"/population": (_weak_claim(2025))},
    )

    assert result.temporal_preference == "conflict"
    assert result.preference == "old"
    assert result.source_preferences["/population"] == "old"


def test_same_year_equal_source_quality_remains_conflict():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2025,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {"/population": (_strong_claim(2025))},
        {"/population": (_strong_claim(2025))},
    )

    assert result.temporal_preference == "conflict"
    assert result.preference == "conflict"
    assert result.source_preferences["/population"] == "same"


def test_same_year_missing_source_quality_remains_conflict():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2025,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {},
        {},
    )

    assert result.temporal_preference == "conflict"
    assert result.preference == "conflict"
    assert result.missing_fields == ("/population",)


def test_quality_aware_identical_candidate_is_same():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    candidate = _quality_candidate(
        100,
        2025,
    )

    result = compare_candidate_with_source_fitness(
        candidate,
        candidate,
        _latest_population_semantics(),
        {},
        {},
    )

    assert result.preference == "same"


def test_quality_aware_comparison_event_is_auditable():
    from verboisy.core.fitness import (
        compare_candidate_with_source_fitness,
    )

    result = compare_candidate_with_source_fitness(
        _quality_candidate(
            100,
            2024,
        ),
        _quality_candidate(
            110,
            2025,
        ),
        _latest_population_semantics(),
        {},
        {},
    )

    event = result.as_event()

    assert event["temporal_preference"] == "new"
    assert event["preference"] == "old"
    assert event["missing_fields"] == ("/population",)


def test_non_temporal_conflict_is_not_resolved_by_source_quality():
    from verboisy.core.fitness import (
        FieldSemantics,
        compare_candidate_with_source_fitness,
    )
    from verboisy.evidence.models import (
        Candidate,
    )

    old = Candidate(
        scope="page",
        record={
            "name": "Example",
            "category": "A",
        },
        evidence={},
        temporal_evidence={},
    )

    new = Candidate(
        scope="page",
        record={
            "name": "Example",
            "category": "B",
        },
        evidence={},
        temporal_evidence={},
    )

    semantics = {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            reference_period="none",
        ),
        "/category": FieldSemantics(
            pointer="/category",
            temporal_class="static",
            reference_period="none",
        ),
    }

    old_quality = _weak_claim(2025)
    new_quality = _strong_claim(2025)

    old_quality = old_quality.__class__(
        **{
            **old_quality.as_event(),
            "pointer": "/category",
        }
    )
    new_quality = new_quality.__class__(
        **{
            **new_quality.as_event(),
            "pointer": "/category",
        }
    )

    result = compare_candidate_with_source_fitness(
        old,
        new,
        semantics,
        {
            "/category": old_quality,
        },
        {
            "/category": new_quality,
        },
    )

    assert result.preference == "conflict"
    assert result.source_preferences == {}


def _dataset_candidate(
    *,
    value=100,
    year=2025,
):
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    temporal = {}

    if year is not None:
        temporal["/value"] = TemporalProof(
            source="period",
            quote=str(year),
            reference_year=year,
        )

    return Candidate(
        scope="entity",
        record={
            "value": value,
        },
        evidence={},
        temporal_evidence=temporal,
    )


def _dataset_semantics(
    *,
    temporal_class="mutable",
    reference_period="required",
    comparable=True,
):
    from verboisy.core.fitness import (
        FieldSemantics,
    )

    return {
        "/value": FieldSemantics(
            pointer="/value",
            temporal_class=temporal_class,
            reference_period=reference_period,
            comparable_across_rows=comparable,
            confidence=1.0,
            basis="model",
        )
    }


def test_dataset_consistency_accepts_same_vintage():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                value=100,
                year=2025,
            ),
            _dataset_candidate(
                value=200,
                year=2025,
            ),
        ],
        _dataset_semantics(),
    )

    assert errors == ()


def test_dataset_consistency_rejects_mixed_vintage():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                value=100,
                year=2024,
            ),
            _dataset_candidate(
                value=200,
                year=2025,
            ),
        ],
        _dataset_semantics(),
    )

    assert errors == ("/value:mixed_reference_periods",)


def test_dataset_consistency_requires_missing_period():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                year=None,
            ),
        ],
        _dataset_semantics(),
    )

    assert errors == ("/value:missing_reference_period",)


def test_dataset_consistency_allows_preferred_missing_period():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                year=None,
            ),
        ],
        _dataset_semantics(
            reference_period="preferred",
        ),
    )

    assert errors == ()


@pytest.mark.parametrize(
    "temporal_class",
    [
        "event",
        "time_series",
    ],
)
def test_dataset_consistency_does_not_force_event_or_series_vintage(
    temporal_class,
):
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                value=100,
                year=2024,
            ),
            _dataset_candidate(
                value=200,
                year=2025,
            ),
        ],
        _dataset_semantics(
            temporal_class=temporal_class,
        ),
    )

    assert errors == ()


def test_dataset_consistency_ignores_static_field():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                year=None,
            ),
        ],
        _dataset_semantics(
            temporal_class="static",
        ),
    )

    assert errors == ()


def test_dataset_consistency_ignores_noncomparable_field():
    from verboisy.core.fitness import (
        dataset_consistency_errors,
    )

    errors = dataset_consistency_errors(
        [
            _dataset_candidate(
                year=2024,
            ),
            _dataset_candidate(
                year=2025,
            ),
        ],
        _dataset_semantics(
            comparable=False,
        ),
    )

    assert errors == ()


def test_dataset_consistency_ignores_null_and_unknown_field():
    from verboisy.core.fitness import (
        FieldSemantics,
        dataset_consistency_errors,
    )
    from verboisy.evidence.models import Candidate

    candidate = Candidate(
        scope="entity",
        record={
            "value": None,
            "other": 10,
        },
        evidence={},
    )

    errors = dataset_consistency_errors(
        [candidate],
        {
            "/value": FieldSemantics(
                pointer="/value",
                temporal_class="mutable",
                reference_period="required",
                comparable_across_rows=True,
            )
        },
    )

    assert errors == ()


def test_dataset_repair_targets_stale_latest_row():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    candidates = [
        _dataset_candidate(
            value=100,
            year=2024,
        ),
        _dataset_candidate(
            value=200,
            year=2025,
        ),
    ]

    semantics = _dataset_semantics()
    semantics["/value"] = replace(
        semantics["/value"],
        temporal_intent=TemporalIntent(
            mode="latest",
        ),
    )

    repairs = dataset_consistency_repair_needs(
        candidates,
        semantics,
    )

    assert len(repairs) == 1

    repair = repairs[0]

    assert repair.candidate_index == 0
    assert repair.pointer == "/value"
    assert repair.reason == ("stale_reference_period")
    assert repair.observed_year == 2024
    assert repair.target_year == 2025
    assert repair.target_mode == "latest"


def test_dataset_repair_targets_missing_latest_period():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    candidates = [
        _dataset_candidate(
            value=100,
            year=None,
        ),
        _dataset_candidate(
            value=200,
            year=2025,
        ),
    ]

    semantics = _dataset_semantics()
    semantics["/value"] = replace(
        semantics["/value"],
        temporal_intent=TemporalIntent(
            mode="latest",
        ),
    )

    repairs = dataset_consistency_repair_needs(
        candidates,
        semantics,
    )

    assert len(repairs) == 1
    assert repairs[0].candidate_index == 0
    assert repairs[0].reason == ("missing_reference_period")
    assert repairs[0].target_year == 2025


def test_dataset_repair_latest_can_have_unknown_target_year():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    semantics = _dataset_semantics()
    semantics["/value"] = replace(
        semantics["/value"],
        temporal_intent=TemporalIntent(
            mode="latest",
        ),
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                year=None,
            ),
        ],
        semantics,
    )

    assert len(repairs) == 1
    assert repairs[0].target_mode == "latest"
    assert repairs[0].target_year is None


def test_dataset_repair_uses_explicit_requested_year():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    semantics = _dataset_semantics()
    semantics["/value"] = replace(
        semantics["/value"],
        temporal_intent=TemporalIntent(
            mode="year",
            start_year=2023,
            end_year=2023,
        ),
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                year=2022,
            ),
        ],
        semantics,
    )

    assert len(repairs) == 1
    assert repairs[0].observed_year == 2022
    assert repairs[0].target_year == 2023
    assert repairs[0].target_mode == "year"


def test_dataset_repair_ignores_non_single_vintage_semantics():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    semantics = _dataset_semantics(
        temporal_class="time_series",
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                year=2024,
            ),
            _dataset_candidate(
                year=2025,
            ),
        ],
        semantics,
    )

    assert repairs == ()


def test_dataset_repair_event_is_serializable():
    from verboisy.core.fitness import (
        DatasetRepairNeed,
    )

    repair = DatasetRepairNeed(
        candidate_index=2,
        pointer="/population",
        reason="stale_reference_period",
        observed_year=2024,
        target_year=2025,
        target_mode="latest",
    )

    assert repair.as_event() == {
        "candidate_index": 2,
        "pointer": "/population",
        "reason": "stale_reference_period",
        "observed_year": 2024,
        "target_year": 2025,
        "target_mode": "latest",
    }


def test_dataset_repair_ignores_null_value():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                value=None,
                year=2025,
            )
        ],
        _dataset_semantics(),
    )

    assert repairs == ()


def test_dataset_repair_ignores_field_without_repairable_intent():
    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                value=100,
                year=2025,
            )
        ],
        _dataset_semantics(),
    )

    assert repairs == ()


def test_dataset_repair_does_not_require_preferred_missing_period():
    from dataclasses import replace

    from verboisy.core.fitness import (
        dataset_consistency_repair_needs,
    )
    from verboisy.core.planner import (
        TemporalIntent,
    )

    semantics = _dataset_semantics(
        reference_period="preferred",
    )

    semantics["/value"] = replace(
        semantics["/value"],
        temporal_intent=TemporalIntent(
            mode="latest",
        ),
    )

    repairs = dataset_consistency_repair_needs(
        [
            _dataset_candidate(
                value=100,
                year=None,
            )
        ],
        semantics,
    )

    assert repairs == ()


def _unit_semantics(
    *,
    unit_sensitive=True,
    comparable=True,
):
    from verboisy.core.fitness import (
        FieldSemantics,
    )

    return {
        "/value": FieldSemantics(
            pointer="/value",
            temporal_class="static",
            unit_sensitive=unit_sensitive,
            comparable_across_rows=comparable,
            confidence=1.0,
            basis="deterministic",
        )
    }


def _unit_observation(
    *,
    dimension="count",
    base_unit="person",
    multiplier=1,
):
    return {
        "record_id": "row",
        "pointer": "/value",
        "canonical_unit": {
            "dimension": dimension,
            "base_unit": base_unit,
            "multiplier": multiplier,
        },
    }


def test_dataset_units_accept_same_identity():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            _unit_observation(),
            _unit_observation(),
        ),
        _unit_semantics(),
    )

    assert errors == ()


def test_dataset_units_detect_mixed_scale():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            _unit_observation(
                multiplier=1,
            ),
            _unit_observation(
                multiplier=1_000,
            ),
        ),
        _unit_semantics(),
    )

    assert errors == ("/value:mixed_unit_scales",)


def test_dataset_units_detect_incompatible_identity():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            _unit_observation(
                dimension="count",
                base_unit="person",
            ),
            _unit_observation(
                dimension="mass",
                base_unit="gram",
            ),
        ),
        _unit_semantics(),
    )

    assert errors == ("/value:incompatible_units",)


def test_dataset_units_report_unknown_canonical_metadata():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            {
                "record_id": "row",
                "pointer": "/value",
                "unit": {
                    "label": "unknown widgets",
                },
            },
        ),
        _unit_semantics(),
    )

    assert errors == ("/value:unknown_unit",)


def test_dataset_units_ignore_non_sensitive_field():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            _unit_observation(),
            _unit_observation(
                dimension="mass",
                base_unit="gram",
            ),
        ),
        _unit_semantics(
            unit_sensitive=False,
        ),
    )

    assert errors == ()


def test_dataset_units_ignore_non_comparable_field():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    errors = dataset_unit_consistency_errors(
        (
            _unit_observation(),
            _unit_observation(
                dimension="mass",
                base_unit="gram",
            ),
        ),
        _unit_semantics(
            comparable=False,
        ),
    )

    assert errors == ()


@pytest.mark.parametrize(
    "canonical",
    [
        None,
        "invalid",
        {
            "dimension": 1,
            "base_unit": "person",
            "multiplier": 1,
        },
        {
            "dimension": "count",
            "base_unit": 1,
            "multiplier": 1,
        },
        {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": 0,
        },
        {
            "dimension": "count",
            "base_unit": "person",
            "multiplier": True,
        },
    ],
)
def test_dataset_units_report_malformed_canonical_identity_as_unknown(
    canonical,
):
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    assert dataset_unit_consistency_errors(
        (
            {
                "record_id": "row",
                "pointer": "/value",
                "canonical_unit": canonical,
            },
        ),
        _unit_semantics(),
    ) == ("/value:unknown_unit",)


def test_dataset_units_ignore_invalid_pointer():
    from verboisy.core.fitness import (
        dataset_unit_consistency_errors,
    )

    assert (
        dataset_unit_consistency_errors(
            (
                {
                    "pointer": 123,
                    "canonical_unit": {
                        "dimension": "count",
                        "base_unit": "person",
                        "multiplier": 1,
                    },
                },
            ),
            _unit_semantics(),
        )
        == ()
    )


@pytest.mark.parametrize("items", [True, False, None])
def test_valid_generic_array_subschemas_have_no_invented_policy(items):
    schema = {"type": "object", "properties": {"rows": {"type": "array"}}}
    if items is not None:
        schema["properties"]["rows"]["items"] = items
    assert scalar_field_schemas(schema) == {}
