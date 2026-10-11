# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Journal grounded scale normalizations without owning the research lifecycle.

Arithmetic and event replay remain in core.units. The caller supplies accepted
comparability observations and owns the borrowed ledger. This workflow keeps raw
accepted evidence intact and writes only the existing unit-normalization events.
"""

from collections.abc import Callable

from verboisy.core.dataset_consistency import Observations
from verboisy.core.fitness import FieldSemantics, dataset_unit_consistency_errors, pointer_pattern
from verboisy.core.source_assessment import source_fitness_candidate_key
from verboisy.core.units import (
    canonical_unit_from_event,
    normalized_unit_value_from_events,
    unit_normalization_event,
)
from verboisy.evidence.models import Candidate
from verboisy.storage.research import ResearchStore


def journal_unit_normalizations(
    store: ResearchStore,
    rid: str,
    field_semantics: dict[str, FieldSemantics],
    observations: Callable[[], Observations],
) -> int:
    """Persist safe deterministic scale normalizations."""

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
    event_method = getattr(
        store,
        "event",
        None,
    )

    if not callable(evidence_method) or not callable(events_method) or not callable(event_method):
        return 0

    accepted_observations = observations()

    errors = dataset_unit_consistency_errors(
        accepted_observations,
        field_semantics,
    )

    mixed_pointers = {
        error.removesuffix(":mixed_unit_scales")
        for error in errors
        if error.endswith(":mixed_unit_scales")
    }

    if not mixed_pointers:
        return 0

    candidates = {
        str(row["record_id"]): (
            Candidate.model_validate(row["candidate"]),
            str(row["snapshot"]["id"]),
        )
        for row in evidence_method(rid)
    }

    normalization_events = events_method(
        rid,
        "unit_normalization",
    )

    created = 0

    for observation in accepted_observations:
        record_id = observation.get("record_id")
        pointer = observation.get("pointer")

        if (
            not isinstance(record_id, str)
            or not isinstance(pointer, str)
            or pointer_pattern(pointer) not in mixed_pointers
        ):
            continue

        unit = canonical_unit_from_event(observation.get("observed_canonical_unit"))

        if unit is None or unit.multiplier == 1:
            continue

        context = candidates.get(record_id)

        if context is None:
            continue
        candidate, snapshot_id = context
        candidate_key = source_fitness_candidate_key(candidate)

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
            continue

        # The replay guard binds the transformation to the accepted raw value,
        # candidate and snapshot. An older row revision must not satisfy it.
        if (
            normalized_unit_value_from_events(
                normalization_events,
                record_id=record_id,
                pointer=pointer,
                original_value=original_value,
                unit=unit,
                candidate_key=candidate_key,
                snapshot_id=snapshot_id,
            )
            is not None
        ):
            continue

        event = unit_normalization_event(
            record_id=record_id,
            pointer=pointer,
            original_value=original_value,
            unit=unit,
            source_unit=observation.get("unit"),
            candidate_key=candidate_key,
            snapshot_id=snapshot_id,
        )

        if event is None:
            continue

        event_method(
            rid,
            "unit_normalization",
            event,
        )

        # Include this successful write in the invocation's replay view so a
        # repeated observation cannot journal the same transformation twice.
        normalization_events.append(
            {
                "payload": event,
            }
        )
        created += 1

    return created
