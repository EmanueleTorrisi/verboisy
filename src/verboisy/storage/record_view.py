# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay grounded unit events into record views without changing saved evidence.

The ledger owns row selection and event reads. This module only projects the
selected inputs; each replacement is checked against the original record before
any value is changed, so a replay cannot accidentally normalize a value twice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from verboisy.core.source_assessment import (
    GroundedClaimComparability,
    source_fitness_candidate_key,
)
from verboisy.core.units import (
    CanonicalUnit,
    canonical_unit,
    normalized_unit_value_from_events,
)
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.evidence.verify import leaves, lookup
from verboisy.extractor.unit_projection import grounded_projected_units


def _replace_pointer_value(
    record: dict[str, Any],
    pointer: str,
    value: object,
) -> bool:
    """Replace an existing JSON-pointer value without creating structure."""

    if not pointer.startswith("/"):
        return False

    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]

    current: Any = record

    for key in parts[:-1]:
        if isinstance(current, list):
            if not key.isdigit():
                return False

            index = int(key)

            if index >= len(current):
                return False

            current = current[index]
            continue

        if isinstance(current, dict):
            if key not in current:
                return False

            current = current[key]
            continue

        return False

    key = parts[-1]

    if isinstance(current, list):
        if not key.isdigit():
            return False

        index = int(key)

        if index >= len(current):
            return False

        current[index] = value
        return True

    if isinstance(current, dict):
        if key not in current:
            return False

        current[key] = value
        return True

    return False


def _apply_unit_normalizations(
    record_id: str,
    record: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    units: Mapping[str, CanonicalUnit],
    candidate_key: str | None = None,
    snapshot_id: str | None = None,
) -> None:
    """Project once per pointer using independently grounded source units."""

    replacements: list[tuple[str, int | float]] = []
    for pointer, unit in units.items():
        try:
            original_value = lookup(record, pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        normalized = normalized_unit_value_from_events(
            events,
            record_id=record_id,
            pointer=pointer,
            original_value=original_value,
            unit=unit,
            candidate_key=candidate_key,
            snapshot_id=snapshot_id,
        )
        if normalized is not None:
            replacements.append((pointer, normalized))

    # Every replay above saw the immutable baseline, never another event's output.
    for pointer, normalized in replacements:
        _replace_pointer_value(record, pointer, normalized)


def normalized_record_view(
    rows: list[dict[str, Any]],
    source_events: list[dict[str, Any]],
    normalization_events: list[dict[str, Any]],
    *,
    claim_comparability_from_events: Callable[..., dict[str, GroundedClaimComparability]],
) -> list[dict[str, Any]]:
    """Project selected records in order using the caller's current claim resolver."""
    result: list[dict[str, Any]] = []
    for row in rows:
        candidate = Candidate.model_validate(row["candidate"])
        page = Snapshot.model_validate(row["snapshot"])
        record_id = str(row["record_id"])
        claims = claim_comparability_from_events(source_events, snapshot=page, candidate=candidate)
        fields = leaves(candidate.record)
        units: dict[str, CanonicalUnit] = {}
        projected_units = grounded_projected_units(candidate, page)
        for pointer, claim in claims.items():
            if pointer not in fields or claim.unit is None or pointer in projected_units:
                continue
            unit = canonical_unit(claim.unit.label)
            if unit is not None:
                units[pointer] = unit

        record = candidate.model_copy(deep=True).record
        _apply_unit_normalizations(
            record_id,
            record,
            normalization_events,
            units=units,
            candidate_key=source_fitness_candidate_key(candidate),
            snapshot_id=page.id,
        )
        result.append({"id": record_id, **record})
    return result
