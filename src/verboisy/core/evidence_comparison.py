# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compare grounded candidates and preserve evidence during metadata repair.

This module reads the caller's ledger and returns the existing comparison result
and mode. Candidate acceptance, identity reconciliation and journal writes remain
with the caller. Source-quality and metadata checks are not research truth claims.
"""

import json
from collections.abc import Callable
from dataclasses import replace

from verboisy.core.fitness import (
    CandidateComparison,
    ClaimFitness,
    FieldSemantics,
    QualityAwareCandidateComparison,
    compare_candidate_fitness,
    compare_candidate_with_source_fitness,
    compare_claim_fitness,
    semantics_for_pointer,
)
from verboisy.core.source_assessment import (
    claim_comparability_from_events,
    source_fitness_from_events,
)
from verboisy.core.units import canonical_unit
from verboisy.evidence.models import Candidate
from verboisy.evidence.verify import leaves
from verboisy.storage.research import ResearchStore


def compare_evidence(
    store: ResearchStore,
    rid: str,
    field_semantics: dict[str, FieldSemantics],
    previous: Candidate,
    previous_snapshot_id: str | None,
    candidate: Candidate,
    current_snapshot_id: str,
    metadata_improves: Callable[..., bool],
) -> tuple[CandidateComparison | QualityAwareCandidateComparison, str]:
    """Compare candidates using persisted source fitness when available."""

    events_method = getattr(
        store,
        "events",
        None,
    )

    if previous_snapshot_id is not None and callable(events_method):
        fitness_events = events_method(
            rid,
            "source_fitness",
        )

        old_fitness = source_fitness_from_events(
            fitness_events,
            snapshot_id=(previous_snapshot_id),
            candidate=previous,
            field_semantics=field_semantics,
        )

        new_fitness = source_fitness_from_events(
            fitness_events,
            snapshot_id=(current_snapshot_id),
            candidate=candidate,
            field_semantics=field_semantics,
        )

        if old_fitness is not None and new_fitness is not None:
            comparison = compare_candidate_with_source_fitness(
                previous,
                candidate,
                field_semantics,
                old_fitness,
                new_fitness,
            )
            if comparison.preference == "same":
                for metadata_kind in ("unit", "definition", "methodology"):
                    if metadata_improves(
                        previous,
                        previous_snapshot_id,
                        candidate,
                        current_snapshot_id,
                        fitness_events,
                        old_fitness,
                        new_fitness,
                        metadata_kind=metadata_kind,
                    ):
                        return replace(comparison, preference="new"), f"{metadata_kind}_repair"
            return comparison, "source_fitness"

    return (
        compare_candidate_fitness(
            previous,
            candidate,
            field_semantics,
        ),
        "temporal_fallback",
    )


def metadata_evidence_improves(
    store: ResearchStore,
    rid: str,
    field_semantics: dict[str, FieldSemantics],
    old: Candidate,
    old_snapshot_id: str,
    new: Candidate,
    new_snapshot_id: str,
    events: list[dict[str, object]],
    old_fitness: dict[str, ClaimFitness],
    new_fitness: dict[str, ClaimFitness],
    *,
    metadata_kind: str = "unit",
) -> bool:
    """Refresh equal values for missing units or definitions without evidence loss."""
    if (
        json.dumps(old.record, sort_keys=True) != json.dumps(new.record, sort_keys=True)
        or old.temporal_evidence != new.temporal_evidence
    ):
        return False
    loader = getattr(store, "load_snapshot", None)
    if not callable(loader):
        return False
    old_page = loader(rid, old_snapshot_id)
    new_page = loader(rid, new_snapshot_id)
    if old_page is None or new_page is None:
        return False
    old_claims = claim_comparability_from_events(events, snapshot=old_page, candidate=old)
    new_claims = claim_comparability_from_events(events, snapshot=new_page, candidate=new)
    improved = False
    for pointer, value in leaves(old.record).items():
        if value is None:
            continue
        if compare_claim_fitness(
            old_fitness.get(pointer, ClaimFitness(pointer)),
            new_fitness.get(pointer, ClaimFitness(pointer)),
            prefer_latest=False,
        ) not in {"same", "new"}:
            return False
        old_metadata = old_claims.get(pointer)
        new_metadata = new_claims.get(pointer)
        for attribute in ("definition", "methodology_identity"):
            before = getattr(old_metadata, attribute, None)
            after = getattr(new_metadata, attribute, None)
            if before is not None and (after is None or before.label != after.label):
                return False
        before_unit = getattr(old_metadata, "unit", None)
        after_unit = getattr(new_metadata, "unit", None)
        old_unit = canonical_unit(before_unit.label) if before_unit else None
        new_unit = canonical_unit(after_unit.label) if after_unit else None
        if old_unit is not None and old_unit != new_unit:
            return False
        semantics = semantics_for_pointer(field_semantics, pointer)
        if (
            metadata_kind == "unit"
            and semantics is not None
            and semantics.unit_sensitive
            and semantics.comparable_across_rows
            and old_unit is None
            and new_unit is not None
        ):
            improved = True
        if (
            metadata_kind == "definition"
            and semantics is not None
            and semantics.definition_sensitive
            and semantics.comparable_across_rows
            and getattr(old_metadata, "definition", None) is None
            and getattr(new_metadata, "definition", None) is not None
        ):
            improved = True
        if (
            metadata_kind == "methodology"
            and semantics is not None
            and semantics.methodology_sensitive
            and semantics.comparable_across_rows
            and getattr(old_metadata, "methodology_identity", None) is None
            and getattr(new_metadata, "methodology_identity", None) is not None
        ):
            improved = True
    return improved
