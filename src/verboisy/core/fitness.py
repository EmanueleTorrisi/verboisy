# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic field semantics and fact-fitness checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from verboisy.core.planner import TemporalIntent
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.evidence.snapshot import whitespace
from verboisy.evidence.verify import leaves

TemporalClass = Literal[
    "static",
    "slow_changing",
    "mutable",
    "event",
    "time_series",
    "unknown",
]

ReferencePeriod = Literal[
    "none",
    "preferred",
    "required",
]

SemanticsBasis = Literal[
    "explicit",
    "deterministic",
    "model",
    "unresolved",
]

_TEMPORAL_CLASSES = {
    "static",
    "slow_changing",
    "mutable",
    "event",
    "time_series",
    "unknown",
}

_REFERENCE_PERIODS = {
    "none",
    "preferred",
    "required",
}

_TEMPORAL_CLASSES_REQUIRING_CONTEXT = {
    "slow_changing",
    "mutable",
    "event",
    "time_series",
}

_SEMANTIC_KEYS = {
    "x-verboisy-temporal-class",
    "x-verboisy-reference-period",
    "x-verboisy-definition-sensitive",
    "x-verboisy-unit-sensitive",
    "x-verboisy-methodology-sensitive",
    "x-verboisy-comparable-across-rows",
}


@dataclass(frozen=True)
class FieldSemantics:
    """Research semantics for one scalar dataset field."""

    pointer: str
    temporal_class: TemporalClass = "unknown"
    reference_period: ReferencePeriod = "none"
    temporal_intent: TemporalIntent | None = None
    definition_sensitive: bool = False
    unit_sensitive: bool = False
    methodology_sensitive: bool = False
    comparable_across_rows: bool = False
    confidence: float = 0.0
    basis: SemanticsBasis = "unresolved"

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def _record_schema(
    schema: dict[str, Any],
) -> dict[str, Any]:
    items = schema.get("items")

    if schema.get("type") == "array" and isinstance(items, dict):
        return items

    return schema


def _escape_pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def scalar_field_schemas(
    schema: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return scalar leaf schemas keyed by wildcard JSON pointer."""

    result: dict[str, dict[str, Any]] = {}

    def walk(
        node: dict[str, Any],
        pointer: str,
    ) -> None:
        if node.get("type") == "array":
            walk(
                node["items"],
                pointer + "/*",
            )
            return

        properties = node.get("properties")

        if isinstance(properties, dict):
            for name, child in properties.items():
                if not isinstance(child, dict):
                    continue

                walk(
                    child,
                    f"{pointer}/{_escape_pointer_part(name)}",
                )

            return

        if pointer:
            result[pointer] = node

    walk(
        _record_schema(schema),
        "",
    )

    return result


def _explicit_semantics(
    pointer: str,
    schema: dict[str, Any],
) -> FieldSemantics:
    temporal_class = schema.get(
        "x-verboisy-temporal-class",
        "unknown",
    )
    reference_period = schema.get(
        "x-verboisy-reference-period",
        "none",
    )

    if temporal_class not in _TEMPORAL_CLASSES:
        temporal_class = "unknown"

    if reference_period not in _REFERENCE_PERIODS:
        reference_period = "none"

    explicit = any(key in schema for key in _SEMANTIC_KEYS)

    return FieldSemantics(
        pointer=pointer,
        temporal_class=temporal_class,
        reference_period=reference_period,
        definition_sensitive=(schema.get("x-verboisy-definition-sensitive") is True),
        unit_sensitive=(schema.get("x-verboisy-unit-sensitive") is True),
        methodology_sensitive=(schema.get("x-verboisy-methodology-sensitive") is True),
        comparable_across_rows=(schema.get("x-verboisy-comparable-across-rows") is True),
        confidence=1.0 if explicit else 0.0,
        basis="explicit" if explicit else "unresolved",
    )


def build_field_semantics(
    schema: dict[str, Any],
) -> dict[str, FieldSemantics]:
    """Build semantics without guessing meaning from field names."""

    return {
        pointer: _explicit_semantics(
            pointer,
            field_schema,
        )
        for pointer, field_schema in scalar_field_schemas(schema).items()
    }


def pointer_pattern(
    pointer: str,
) -> str:
    """Normalize concrete array indices to wildcard schema pointers."""

    return "/".join("*" if part.isdigit() else part for part in pointer.split("/"))


def semantics_for_pointer(
    semantics: dict[str, FieldSemantics],
    pointer: str,
) -> FieldSemantics | None:
    return semantics.get(pointer_pattern(pointer))


def requires_temporal_evidence(
    semantics: FieldSemantics,
    intent: TemporalIntent,
) -> bool:
    """Return whether this field has a hard reference-period requirement."""

    # The global request timeframe must not make unrelated fields mandatory.
    # Field-scoped planning decides which fields require temporal provenance.
    _ = intent

    return semantics.reference_period == "required"


def mutable_field_patterns(
    schema: dict[str, Any],
) -> list[str]:
    """Compatibility view for extraction prompts.

    Field-name guessing is intentionally not performed here.
    """

    semantics = build_field_semantics(schema)

    return sorted(
        pointer
        for pointer, field in semantics.items()
        if field.temporal_class in _TEMPORAL_CLASSES_REQUIRING_CONTEXT
    )


def is_mutable_pointer(
    schema: dict[str, Any],
    pointer: str,
) -> bool:
    """Compatibility helper backed by FieldSemantics."""

    semantics = semantics_for_pointer(
        build_field_semantics(schema),
        pointer,
    )

    return bool(semantics and semantics.temporal_class in _TEMPORAL_CLASSES_REQUIRING_CONTEXT)


def temporal_errors(
    candidate: Candidate,
    page: Snapshot,
    schema: dict[str, Any],
    intent: TemporalIntent,
    *,
    current_year: int,
    field_semantics: (dict[str, FieldSemantics] | None) = None,
) -> list[str]:
    """Validate temporal provenance using explicit field semantics."""

    semantics = field_semantics if field_semantics is not None else build_field_semantics(schema)

    fields = leaves(candidate.record)
    sources = {source.id: source for source in page.sources}
    errors: list[str] = []

    if set(candidate.temporal_evidence) - set(fields):
        errors.append("unknown_temporal_evidence_pointer")

    for pointer, value in fields.items():
        if value is None:
            continue

        field = semantics_for_pointer(
            semantics,
            pointer,
        )

        if field is None:
            continue

        proof = candidate.temporal_evidence.get(pointer)
        required = requires_temporal_evidence(
            field,
            intent,
        )

        if proof is None:
            if required:
                errors.append(f"{pointer}:" "missing_temporal_evidence")

            continue

        source = sources.get(proof.source)

        if source is None or source.scope not in {
            candidate.scope,
            "page",
        }:
            errors.append(f"{pointer}:" "temporal_source_outside_scope")
            continue

        quote = whitespace(proof.quote)
        observed = whitespace(source.text)

        if (
            not quote
            or quote not in observed
            or re.search(
                rf"(?<!\d)" rf"{proof.reference_year}" rf"(?!\d)",
                quote,
            )
            is None
        ):
            errors.append(f"{pointer}:" "temporal_quote_not_observed")
            continue

        year = proof.reference_year
        effective_intent = field.temporal_intent or intent

        if effective_intent.mode == "latest" and year > current_year:
            errors.append(f"{pointer}:" "future_temporal_value")

        elif (
            (effective_intent.mode == "year" and year != effective_intent.start_year)
            or effective_intent.mode == "range"
            and (
                effective_intent.start_year is None
                or effective_intent.end_year is None
                or not effective_intent.start_year <= year <= effective_intent.end_year
            )
        ):
            errors.append(f"{pointer}:temporal_mismatch")

    return errors


CandidatePreference = Literal[
    "same",
    "new",
    "old",
    "conflict",
]


@dataclass(frozen=True)
class CandidateComparison:
    """Deterministic comparison of two validated candidates."""

    preference: CandidatePreference
    changed_fields: tuple[str, ...]
    newer_fields: tuple[str, ...]
    older_fields: tuple[str, ...]
    unresolved_fields: tuple[str, ...]

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def compare_candidate_fitness(
    old: Candidate,
    new: Candidate,
    field_semantics: dict[str, FieldSemantics],
) -> CandidateComparison:
    """Compare validated candidates without inventing source authority.

    Supersession is allowed only when every changed field is provably
    ordered in the same direction by field-scoped `latest` temporal
    evidence.

    Static, historical, undated, equally dated, or mixed-direction
    disagreements remain unresolved conflicts.
    """

    old_fields = leaves(old.record)
    new_fields = leaves(new.record)

    changed = sorted(
        pointer
        for pointer in set(old_fields) | set(new_fields)
        if old_fields.get(pointer) != new_fields.get(pointer)
    )

    compared = set(changed)
    for pointer in old_fields.keys() & new_fields.keys():
        semantics = semantics_for_pointer(field_semantics, pointer)
        old_proof = old.temporal_evidence.get(pointer)
        new_proof = new.temporal_evidence.get(pointer)
        if (
            semantics is not None
            and semantics.temporal_intent is not None
            and semantics.temporal_intent.mode == "latest"
            and old_proof is not None
            and new_proof is not None
            and old_proof.reference_year != new_proof.reference_year
        ):
            compared.add(pointer)

    if not compared:
        return CandidateComparison(
            preference="same",
            changed_fields=(),
            newer_fields=(),
            older_fields=(),
            unresolved_fields=(),
        )

    newer: list[str] = []
    older: list[str] = []
    unresolved: list[str] = []

    for pointer in sorted(compared):
        semantics = semantics_for_pointer(
            field_semantics,
            pointer,
        )

        if (
            semantics is None
            or semantics.temporal_intent is None
            or semantics.temporal_intent.mode != "latest"
        ):
            unresolved.append(pointer)
            continue

        old_proof = old.temporal_evidence.get(pointer)
        new_proof = new.temporal_evidence.get(pointer)

        if old_proof is None or new_proof is None:
            unresolved.append(pointer)
            continue

        if new_proof.reference_year > old_proof.reference_year:
            newer.append(pointer)
        elif new_proof.reference_year < old_proof.reference_year:
            older.append(pointer)
        else:
            # Different values attributed to the same reference period
            # are disagreement, not freshness.
            unresolved.append(pointer)

    if newer and not older and not unresolved:
        preference: CandidatePreference = "new"
    elif older and not newer and not unresolved:
        preference = "old"
    else:
        preference = "conflict"

    return CandidateComparison(
        preference=preference,
        changed_fields=tuple(changed),
        newer_fields=tuple(newer),
        older_fields=tuple(older),
        unresolved_fields=tuple(unresolved),
    )


AuthorityLevel = Literal[
    "unknown",
    "general",
    "specialist",
    "responsible",
]

DirectnessLevel = Literal[
    "unknown",
    "tertiary",
    "secondary",
    "primary",
]

MethodologyLevel = Literal[
    "unknown",
    "absent",
    "partial",
    "explicit",
]

ProvenanceLevel = Literal[
    "unknown",
    "opaque",
    "attributed",
    "traceable",
]


_AUTHORITY_RANK = {
    "unknown": 0,
    "general": 1,
    "specialist": 2,
    "responsible": 3,
}

_DIRECTNESS_RANK = {
    "unknown": 0,
    "tertiary": 1,
    "secondary": 2,
    "primary": 3,
}

_METHODOLOGY_RANK = {
    "unknown": 0,
    "absent": 0,
    "partial": 1,
    "explicit": 2,
}

_PROVENANCE_RANK = {
    "unknown": 0,
    "opaque": 0,
    "attributed": 1,
    "traceable": 2,
}


@dataclass(frozen=True)
class ClaimFitness:
    """Claim-specific source/evidence quality.

    These dimensions describe the source's relationship to one claim,
    not a permanent reputation score for the domain or publisher.
    """

    pointer: str
    authority: AuthorityLevel = "unknown"
    directness: DirectnessLevel = "unknown"
    methodology: MethodologyLevel = "unknown"
    provenance: ProvenanceLevel = "unknown"
    corroboration: int = 0
    reference_year: int | None = None

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def claim_fitness_vector(
    fitness: ClaimFitness,
    *,
    prefer_latest: bool,
) -> tuple[int, ...]:
    """Return an ordinal vector without collapsing dimensions."""

    base = (
        _AUTHORITY_RANK[fitness.authority],
        _DIRECTNESS_RANK[fitness.directness],
        _METHODOLOGY_RANK[fitness.methodology],
        _PROVENANCE_RANK[fitness.provenance],
        max(0, fitness.corroboration),
    )

    if not prefer_latest:
        return base

    return (
        *base,
        (fitness.reference_year if fitness.reference_year is not None else -1),
    )


def compare_claim_fitness(
    old: ClaimFitness,
    new: ClaimFitness,
    *,
    prefer_latest: bool,
) -> CandidatePreference:
    """Compare claim fitness by Pareto dominance.

    A candidate wins only if it is at least as strong in every
    considered dimension and strictly stronger in one or more.

    Mixed tradeoffs remain unresolved rather than being hidden by
    arbitrary weights.
    """

    if old.pointer != new.pointer:
        raise ValueError("cannot compare fitness for different claims")

    old_vector = claim_fitness_vector(
        old,
        prefer_latest=prefer_latest,
    )
    new_vector = claim_fitness_vector(
        new,
        prefer_latest=prefer_latest,
    )

    if old_vector == new_vector:
        return "same"

    new_dominates = all(
        new_value >= old_value
        for old_value, new_value in zip(
            old_vector,
            new_vector,
            strict=True,
        )
    )

    old_dominates = all(
        old_value >= new_value
        for old_value, new_value in zip(
            old_vector,
            new_vector,
            strict=True,
        )
    )

    if new_dominates:
        return "new"

    if old_dominates:
        return "old"

    return "conflict"


@dataclass(frozen=True)
class QualityAwareCandidateComparison:
    """Temporal candidate comparison gated by claim source fitness."""

    preference: CandidatePreference
    temporal_preference: CandidatePreference
    changed_fields: tuple[str, ...]
    source_preferences: dict[
        str,
        CandidatePreference,
    ]
    blocked_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def claim_fitness_has_quality_signal(
    fitness: ClaimFitness,
) -> bool:
    """Return whether source assessment established useful quality.

    Reference year is intentionally excluded because temporal
    fitness is handled separately.
    """

    return any(
        (
            fitness.authority != "unknown",
            fitness.directness != "unknown",
            fitness.methodology
            not in {
                "unknown",
                "absent",
            },
            fitness.provenance
            not in {
                "unknown",
                "opaque",
            },
            fitness.corroboration > 0,
        )
    )


def _is_same_period_conflict(
    old: Candidate,
    new: Candidate,
    comparison: CandidateComparison,
    field_semantics: dict[
        str,
        FieldSemantics,
    ],
) -> bool:
    """Return whether every changed claim conflicts in the same latest period."""

    if (
        comparison.preference != "conflict"
        or not comparison.changed_fields
        or comparison.newer_fields
        or comparison.older_fields
    ):
        return False

    for pointer in comparison.changed_fields:
        semantics = semantics_for_pointer(
            field_semantics,
            pointer,
        )
        old_proof = old.temporal_evidence.get(pointer)
        new_proof = new.temporal_evidence.get(pointer)

        if (
            semantics is None
            or semantics.temporal_intent is None
            or semantics.temporal_intent.mode != "latest"
            or old_proof is None
            or new_proof is None
            or old_proof.reference_year != new_proof.reference_year
        ):
            return False

    return True


def compare_candidate_with_source_fitness(
    old: Candidate,
    new: Candidate,
    field_semantics: dict[
        str,
        FieldSemantics,
    ],
    old_fitness: dict[
        str,
        ClaimFitness,
    ],
    new_fitness: dict[
        str,
        ClaimFitness,
    ],
) -> QualityAwareCandidateComparison:
    """Combine temporal preference with grounded source quality.

    Newer candidates may supersede only when their source quality is
    not materially worse.

    Same-period disagreements may be resolved when one side strictly
    dominates source quality across all changed claims.

    Other temporal or semantic conflicts remain unresolved.
    """

    temporal = compare_candidate_fitness(
        old,
        new,
        field_semantics,
    )

    same_period = _is_same_period_conflict(
        old,
        new,
        temporal,
        field_semantics,
    )

    if temporal.preference not in {
        "new",
        "conflict",
    } or (temporal.preference == "conflict" and not same_period):
        return QualityAwareCandidateComparison(
            preference=temporal.preference,
            temporal_preference=(temporal.preference),
            changed_fields=(temporal.changed_fields),
            source_preferences={},
            blocked_fields=(),
            missing_fields=(),
        )

    source_preferences: dict[
        str,
        CandidatePreference,
    ] = {}
    blocked: list[str] = []
    missing: list[str] = []

    for pointer in sorted(set(temporal.changed_fields) | set(temporal.newer_fields)):
        old_claim = old_fitness.get(pointer)
        new_claim = new_fitness.get(pointer)

        if old_claim is None or new_claim is None:
            missing.append(pointer)
            continue

        if not claim_fitness_has_quality_signal(old_claim) or not claim_fitness_has_quality_signal(
            new_claim
        ):
            missing.append(pointer)
            continue

        preference = compare_claim_fitness(
            old_claim,
            new_claim,
            prefer_latest=False,
        )

        source_preferences[pointer] = preference

        if preference in {
            "old",
            "conflict",
        }:
            blocked.append(pointer)

    if temporal.preference == "new":
        final_preference: CandidatePreference = "old" if missing or blocked else "new"

    elif missing:
        final_preference = "conflict"

    else:
        preferences = set(source_preferences.values())

        if (
            preferences
            <= {
                "same",
                "new",
            }
            and "new" in preferences
        ):
            final_preference = "new"

        elif (
            preferences
            <= {
                "same",
                "old",
            }
            and "old" in preferences
        ):
            final_preference = "old"

        else:
            final_preference = "conflict"

    return QualityAwareCandidateComparison(
        preference=final_preference,
        temporal_preference=(temporal.preference),
        changed_fields=(temporal.changed_fields),
        source_preferences=(source_preferences),
        blocked_fields=tuple(blocked),
        missing_fields=tuple(missing),
    )


_DATASET_SINGLE_VINTAGE_CLASSES = {
    "slow_changing",
    "mutable",
}


def dataset_consistency_errors(
    candidates: list[Candidate],
    field_semantics: dict[str, FieldSemantics],
) -> tuple[str, ...]:
    """Return deterministic cross-row comparability gaps.

    Only snapshot-like fields require one shared vintage. Event and
    time-series fields may legitimately contain different periods.
    """

    missing_periods: set[str] = set()
    reference_years: dict[str, set[int]] = {}

    for candidate in candidates:
        for pointer, value in leaves(candidate.record).items():
            if value is None:
                continue

            semantics = semantics_for_pointer(
                field_semantics,
                pointer,
            )

            if semantics is None or not semantics.comparable_across_rows:
                continue

            if semantics.temporal_class == "static":
                continue

            proof = candidate.temporal_evidence.get(pointer)

            if proof is None:
                if semantics.reference_period == "required":
                    missing_periods.add(semantics.pointer)

                continue

            if semantics.temporal_class not in _DATASET_SINGLE_VINTAGE_CLASSES:
                continue

            reference_years.setdefault(
                semantics.pointer,
                set(),
            ).add(proof.reference_year)

    errors = {f"{pointer}:missing_reference_period" for pointer in missing_periods}

    errors.update(
        f"{pointer}:mixed_reference_periods"
        for pointer, years in reference_years.items()
        if len(years) > 1
    )

    return tuple(sorted(errors))


DatasetRepairReason = Literal[
    "missing_reference_period",
    "stale_reference_period",
]


@dataclass(frozen=True)
class DatasetRepairNeed:
    """One deterministic cross-row repair requirement."""

    candidate_index: int
    pointer: str
    reason: DatasetRepairReason
    observed_year: int | None
    target_year: int | None
    target_mode: Literal["latest", "year"]

    def as_event(self) -> dict[str, object]:
        return asdict(self)


def dataset_consistency_repair_needs(
    candidates: list[Candidate],
    field_semantics: dict[str, FieldSemantics],
) -> tuple[DatasetRepairNeed, ...]:
    """Plan repairs for deterministically resolvable vintage gaps."""

    observations: dict[
        str,
        list[tuple[int, int | None]],
    ] = {}

    comparable: dict[str, FieldSemantics] = {}

    for candidate_index, candidate in enumerate(candidates):
        for pointer, value in leaves(candidate.record).items():
            if value is None:
                continue

            semantics = semantics_for_pointer(
                field_semantics,
                pointer,
            )

            if (
                semantics is None
                or not semantics.comparable_across_rows
                or semantics.temporal_class not in _DATASET_SINGLE_VINTAGE_CLASSES
            ):
                continue

            comparable[semantics.pointer] = semantics

            proof = candidate.temporal_evidence.get(pointer)

            observations.setdefault(
                semantics.pointer,
                [],
            ).append(
                (
                    candidate_index,
                    (proof.reference_year if proof is not None else None),
                )
            )

    repairs: list[DatasetRepairNeed] = []

    for pointer in sorted(observations):
        semantics = comparable[pointer]
        values = observations[pointer]

        years = {year for _, year in values if year is not None}

        intent = semantics.temporal_intent

        target_mode: (
            Literal[
                "latest",
                "year",
            ]
            | None
        ) = None
        target_year: int | None = None

        if intent is not None and intent.mode == "year" and intent.start_year is not None:
            target_mode = "year"
            target_year = intent.start_year

        elif intent is not None and intent.mode == "latest":
            target_mode = "latest"

            if years:
                target_year = max(years)

        else:
            continue

        for candidate_index, observed_year in values:
            if observed_year is None:
                if semantics.reference_period == "required":
                    repairs.append(
                        DatasetRepairNeed(
                            candidate_index=candidate_index,
                            pointer=pointer,
                            reason=("missing_reference_period"),
                            observed_year=None,
                            target_year=target_year,
                            target_mode=target_mode,
                        )
                    )

                continue

            if target_year is not None and observed_year != target_year:
                repairs.append(
                    DatasetRepairNeed(
                        candidate_index=candidate_index,
                        pointer=pointer,
                        reason=("stale_reference_period"),
                        observed_year=observed_year,
                        target_year=target_year,
                        target_mode=target_mode,
                    )
                )

    return tuple(repairs)


def _canonical_unit_key(
    value: object,
) -> tuple[str, str, int] | None:
    """Decode one internally generated canonical-unit observation."""

    if not isinstance(value, dict):
        return None

    dimension = value.get("dimension")
    base_unit = value.get("base_unit")
    multiplier = value.get("multiplier")

    if not isinstance(dimension, str):
        return None

    if not isinstance(base_unit, str):
        return None

    if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 0:
        return None

    return (
        dimension,
        base_unit,
        multiplier,
    )


def dataset_unit_consistency_errors(
    observations: tuple[
        dict[str, object],
        ...,
    ],
    field_semantics: dict[
        str,
        FieldSemantics,
    ],
) -> tuple[str, ...]:
    """Return deterministic grounded unit-comparability gaps."""

    units: dict[
        str,
        set[tuple[str, str, int]],
    ] = {}

    errors: set[str] = set()

    for observation in observations:
        pointer = observation.get("pointer")

        if not isinstance(pointer, str):
            continue

        semantics = semantics_for_pointer(
            field_semantics,
            pointer,
        )

        if (
            semantics is None
            or not semantics.comparable_across_rows
            or not semantics.unit_sensitive
        ):
            continue

        key = _canonical_unit_key(observation.get("canonical_unit"))

        # Unknown identity is unresolved, not proof of incompatibility.
        if key is None:
            errors.add(f"{semantics.pointer}:unknown_unit")
            continue

        units.setdefault(
            semantics.pointer,
            set(),
        ).add(key)

    for pointer, observed in units.items():
        identities = {
            (
                dimension,
                base_unit,
            )
            for (
                dimension,
                base_unit,
                _multiplier,
            ) in observed
        }

        if len(identities) > 1:
            errors.add(f"{pointer}:incompatible_units")
            continue

        multipliers = {
            multiplier
            for (
                _dimension,
                _base_unit,
                multiplier,
            ) in observed
        }

        if len(multipliers) > 1:
            errors.add(f"{pointer}:mixed_unit_scales")

    return tuple(sorted(errors))


def dataset_definition_consistency_errors(
    observations: tuple[dict[str, object], ...],
    field_semantics: dict[str, FieldSemantics],
) -> tuple[str, ...]:
    """Require grounded literal definition agreement; differing labels stay unresolved."""
    definitions: dict[str, set[str]] = {}
    errors: set[str] = set()
    for observation in observations:
        pointer = observation.get("pointer")
        if not isinstance(pointer, str):
            continue
        semantics = semantics_for_pointer(field_semantics, pointer)
        if (
            semantics is None
            or not semantics.comparable_across_rows
            or not semantics.definition_sensitive
        ):
            continue
        descriptor = observation.get("definition")
        label = descriptor.get("label") if isinstance(descriptor, dict) else None
        if not isinstance(label, str) or not label.strip():
            errors.add(f"{semantics.pointer}:unknown_definition")
            continue
        definitions.setdefault(semantics.pointer, set()).add(label)
    errors.update(
        f"{pointer}:unresolved_definitions"
        for pointer, labels in definitions.items()
        if len(labels) > 1
    )
    return tuple(sorted(errors))


def dataset_methodology_consistency_errors(
    observations: tuple[dict[str, object], ...],
    field_semantics: dict[str, FieldSemantics],
) -> tuple[str, ...]:
    """Require grounded literal methodology agreement; differing labels stay unresolved."""
    methodologies: dict[str, set[str]] = {}
    errors: set[str] = set()
    for observation in observations:
        pointer = observation.get("pointer")
        if not isinstance(pointer, str):
            continue
        semantics = semantics_for_pointer(field_semantics, pointer)
        if (
            semantics is None
            or not semantics.comparable_across_rows
            or not semantics.methodology_sensitive
        ):
            continue
        descriptor = observation.get("methodology_identity")
        label = descriptor.get("label") if isinstance(descriptor, dict) else None
        if not isinstance(label, str) or not label.strip():
            errors.add(f"{semantics.pointer}:unknown_methodology")
            continue
        methodologies.setdefault(semantics.pointer, set()).add(label)
    errors.update(
        f"{pointer}:unresolved_methodologies"
        for pointer, labels in methodologies.items()
        if len(labels) > 1
    )
    return tuple(sorted(errors))
