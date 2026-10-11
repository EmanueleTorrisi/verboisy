# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Recover display units from accepted bindings, never from column names."""

from __future__ import annotations

import re
from typing import Any

from verboisy.core.source_assessment import (
    claim_comparability_from_events,
    source_fitness_candidate_key,
)
from verboisy.core.units import canonical_unit, normalized_unit_value_from_events
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.evidence.verify import leaves
from verboisy.extractor.unit_projection import grounded_projected_units
from verboisy.storage.research import ResearchStore


def output_numeric_units(
    store: ResearchStore, rid: str, mappings: list[dict[str, Any]]
) -> dict[tuple[Any, str], dict[str, Any]]:
    """Bind effective units to output cells, requiring agreement across contributors.

    Replaying the normalization event is essential even when raw and effective
    values compare equal: zero kilograms normalized to grams is still zero.
    """
    units: dict[str, dict[str, dict[str, Any]]] = {}
    events = store.events(rid, "source_fitness")
    normalizations = store.events(rid, "unit_normalization")
    for context in store.evidence(rid):
        if "candidate" not in context or "snapshot" not in context:
            continue
        record_id = str(context["record_id"])
        candidate = Candidate.model_validate(context["candidate"])
        snapshot = Snapshot.model_validate(context["snapshot"])
        sources = {source.id: source.text for source in snapshot.sources}
        fields = leaves(candidate.record)
        bindings: dict[str, dict[str, Any]] = {}
        projected = grounded_projected_units(candidate, snapshot)
        for pointer, unit in projected.items():
            bindings[pointer] = {
                "label": unit.canonical_unit.base_unit,
                "basis": "dataset_unit_projection",
                "source_pointer": unit.unit_pointer,
                "source_label": unit.observed_unit_label,
                "snapshot_id": snapshot.id,
            }
        claims = claim_comparability_from_events(events, snapshot=snapshot, candidate=candidate)
        for pointer, claim in claims.items():
            if (
                pointer not in fields
                or claim.unit is None
                or pointer in projected
                or isinstance(fields[pointer], bool)
                or not isinstance(fields[pointer], int | float)
            ):
                continue
            label = claim.unit.label
            # An observed short label must not conceal a scale or a rate. Some
            # display units (for example pounds) have no canonical ledger scale.
            observed = sources[claim.unit.source]
            escaped = re.escape(label)
            if re.search(
                rf"(?:hundreds?|thousands?|millions?|billions?)(?: of)?\s+{escaped}\b"
                rf"|\b{escaped}\s*(?:/|per\b|[²³]|\^)",
                observed,
                re.IGNORECASE,
            ):
                continue
            canonical = canonical_unit(label)
            normalized = (
                normalized_unit_value_from_events(
                    normalizations,
                    record_id=record_id,
                    pointer=pointer,
                    original_value=fields[pointer],
                    unit=canonical,
                    candidate_key=source_fitness_candidate_key(candidate),
                    snapshot_id=snapshot.id,
                )
                if canonical is not None
                else None
            )
            bindings[pointer] = {
                "label": canonical.base_unit
                if canonical is not None and normalized is not None
                else label,
                "basis": "unit_normalization" if normalized is not None else "source_unit",
                "source": claim.unit.as_event(),
                "snapshot_id": snapshot.id,
            }
        units[record_id] = bindings
    result: dict[tuple[Any, str], dict[str, Any]] = {}
    for mapping in mappings:
        ids = mapping.get("record_ids", [mapping.get("record_id")])
        contributors = [units.get(record_id, {}) for record_id in ids]
        if not contributors:
            continue
        for pointer, binding in contributors[0].items():
            # Missing or differing units forbid a grouped conversion. The existing
            # aggregation remains visible; presentation cannot repair comparability.
            if all(item.get(pointer, {}).get("label") == binding["label"] for item in contributors):
                result[(mapping["output_id"], pointer)] = {
                    "label": binding["label"],
                    "bindings": [item[pointer] for item in contributors],
                }
    return result
