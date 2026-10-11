# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect accepted evidence and derive row-specific dataset repair requests.

Inspection reads the borrowed ledger and returns fresh observations; it neither
accepts candidates nor discovers sources. Runner callbacks preserve the existing
observation hook and read order without importing the research orchestrator.
"""

from collections.abc import Callable
from dataclasses import replace

from verboisy.core.fitness import (
    FieldSemantics,
    dataset_consistency_errors,
    dataset_consistency_repair_needs,
    dataset_definition_consistency_errors,
    dataset_methodology_consistency_errors,
    dataset_unit_consistency_errors,
    semantics_for_pointer,
)
from verboisy.core.planner import TemporalIntent
from verboisy.core.source_assessment import (
    claim_comparability_from_events,
    source_fitness_candidate_key,
)
from verboisy.core.units import (
    CanonicalUnit,
    canonical_unit,
    normalized_unit_value_from_events,
)
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.evidence.verify import leaves
from verboisy.extractor.descriptor_projection import grounded_projected_descriptors
from verboisy.extractor.unit_projection import grounded_projected_units
from verboisy.storage.research import ResearchStore

Observations = tuple[dict[str, object], ...]


def accepted_comparability_observations(
    store: ResearchStore, rid: str, field_semantics: dict[str, FieldSemantics]
) -> Observations:
    """Return grounded metadata attached to accepted rows."""

    evidence_method = getattr(
        store,
        "evidence",
        None,
    )
    events_method = getattr(
        store,
        "events",
        None,
    )

    if not callable(evidence_method) or not callable(events_method):
        return ()

    source_events = events_method(
        rid,
        "source_fitness",
    )
    normalization_events = events_method(
        rid,
        "unit_normalization",
    )

    observations: list[dict[str, object]] = []

    for row in evidence_method(rid):
        candidate = Candidate.model_validate(row["candidate"])
        accepted_snapshot = Snapshot.model_validate(row["snapshot"])
        record_id = str(row["record_id"])

        claims = claim_comparability_from_events(
            source_events,
            snapshot=accepted_snapshot,
            candidate=candidate,
        )

        projected_units = grounded_projected_units(candidate, accepted_snapshot)
        projected_descriptors = grounded_projected_descriptors(candidate, accepted_snapshot)
        required_pointers: set[str] = set()
        for pointer, value in leaves(candidate.record).items():
            semantics = semantics_for_pointer(field_semantics, pointer)
            if (
                value is not None
                and semantics is not None
                and (
                    semantics.unit_sensitive
                    or semantics.definition_sensitive
                    or semantics.methodology_sensitive
                )
                and semantics.comparable_across_rows
            ):
                required_pointers.add(pointer)

        for pointer in sorted(
            set(claims) | required_pointers | set(projected_units) | set(projected_descriptors)
        ):
            comparability = claims.get(pointer)
            payload = comparability.as_event() if comparability is not None else {}

            if (
                not payload
                and pointer not in required_pointers
                and pointer not in projected_units
                and pointer not in projected_descriptors
            ):
                continue

            observation: dict[str, object] = {
                "record_id": record_id,
                "pointer": pointer,
                **payload,
            }

            unit_payload = payload.get("unit")

            if isinstance(unit_payload, dict):
                label = unit_payload.get("label")

                if isinstance(label, str):
                    canonical = canonical_unit(label)

                    if canonical is not None:
                        observation["observed_canonical_unit"] = canonical.as_event()
                        observation["canonical_unit"] = canonical.as_event()

                        try:
                            from verboisy.evidence.verify import lookup

                            original_value = lookup(
                                candidate.record,
                                pointer,
                            )
                        except (
                            KeyError,
                            IndexError,
                            TypeError,
                            ValueError,
                        ):
                            original_value = None

                        # Normalization replay must match this accepted candidate
                        # and snapshot; an older event cannot supply fresh evidence.
                        normalized = normalized_unit_value_from_events(
                            normalization_events,
                            record_id=record_id,
                            pointer=pointer,
                            original_value=original_value,
                            unit=canonical,
                            candidate_key=source_fitness_candidate_key(candidate),
                            snapshot_id=accepted_snapshot.id,
                        )

                        if normalized is not None:
                            observation["normalized_value"] = normalized
                            observation["canonical_unit"] = CanonicalUnit(
                                dimension=canonical.dimension,
                                base_unit=canonical.base_unit,
                                multiplier=1,
                            ).as_event()

            projected_unit = projected_units.get(pointer)
            if projected_unit is not None:
                observation["observed_canonical_unit"] = projected_unit.canonical_unit.as_event()
                observation["canonical_unit"] = projected_unit.canonical_unit.as_event()
                observation["normalized_value"] = projected_unit.value
                observation["dataset_unit_projection"] = {
                    "value_pointer": projected_unit.value_pointer,
                    "unit_pointer": projected_unit.unit_pointer,
                    "observed_label": projected_unit.observed_unit_label,
                }
            for kind, descriptor in projected_descriptors.get(pointer, {}).items():
                key = "definition" if kind == "definition" else "methodology_identity"
                observation[key] = {
                    "label": descriptor.observed_label,
                    "source": descriptor.descriptor_pointer,
                    "quote": descriptor.descriptor_value_json,
                }
            observations.append(observation)

    return tuple(observations)


def accepted_consistency_gaps(
    store: ResearchStore,
    rid: str,
    field_semantics: dict[str, FieldSemantics],
    observations: Callable[[], Observations],
) -> tuple[str, ...]:
    """Return deterministic gaps across accepted rows."""

    evidence_method = getattr(
        store,
        "evidence",
        None,
    )

    temporal_errors: tuple[str, ...] = ()

    if callable(evidence_method):
        candidates = [Candidate.model_validate(row["candidate"]) for row in evidence_method(rid)]

        temporal_errors = dataset_consistency_errors(
            candidates,
            field_semantics,
        )

    accepted_observations = observations()
    unit_errors = dataset_unit_consistency_errors(accepted_observations, field_semantics)
    definition_errors = dataset_definition_consistency_errors(
        accepted_observations, field_semantics
    )
    methodology_errors = dataset_methodology_consistency_errors(
        accepted_observations, field_semantics
    )

    return tuple(
        sorted(
            {
                *temporal_errors,
                *unit_errors,
                *definition_errors,
                *methodology_errors,
            }
        )
    )


def accepted_consistency_repairs(
    store: ResearchStore,
    rid: str,
    field_semantics: dict[str, FieldSemantics],
    temporal_intent: TemporalIntent | None,
    declared_datasets: bool,
    observations: Callable[[], Observations],
) -> Observations:
    """Return row-scoped deterministic repair needs."""

    evidence_method = getattr(
        store,
        "evidence",
        None,
    )

    if not callable(evidence_method):
        return ()

    evidence_rows = evidence_method(rid)

    candidates = [Candidate.model_validate(row["candidate"]) for row in evidence_rows]

    repair_semantics = field_semantics
    if declared_datasets:
        # Fill required temporal context for declared datasets without mutating
        # the saved field semantics or changing ordinary page-research policy.
        repair_semantics = {
            pointer: replace(field, temporal_intent=temporal_intent)
            if field.temporal_intent is None
            and field.reference_period == "required"
            and field.temporal_class in {"mutable", "slow_changing"}
            else field
            for pointer, field in field_semantics.items()
        }
    needs = dataset_consistency_repair_needs(candidates, repair_semantics)

    repairs = [
        {
            "record_id": str(evidence_rows[need.candidate_index]["record_id"]),
            **need.as_event(),
            **(
                {
                    "candidate_key": source_fitness_candidate_key(candidates[need.candidate_index]),
                    "snapshot_id": evidence_rows[need.candidate_index]["snapshot"]["id"],
                }
                if declared_datasets
                else {}
            ),
        }
        for need in needs
    ]
    indexes = {str(row["record_id"]): index for index, row in enumerate(evidence_rows)}
    for observation in observations():
        for mode, check in (
            ("unit", dataset_unit_consistency_errors),
            ("definition", dataset_definition_consistency_errors),
            ("methodology", dataset_methodology_consistency_errors),
        ):
            reason = f"unknown_{mode}"
            errors = check((observation,), field_semantics)
            if not any(error.endswith(f":{reason}") for error in errors):
                continue
            record_id = str(observation["record_id"])
            index = indexes[record_id]
            repairs.append(
                {
                    "record_id": record_id,
                    "candidate_index": index,
                    "pointer": observation["pointer"],
                    "reason": reason,
                    "observed_year": None,
                    "target_year": None,
                    "target_mode": mode,
                    "candidate_key": source_fitness_candidate_key(candidates[index]),
                    "snapshot_id": evidence_rows[index]["snapshot"]["id"],
                }
            )
    return tuple(repairs)
