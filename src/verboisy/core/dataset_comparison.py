# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compare projected dataset rows without discarding grounded metadata.

The caller lends its run context and verification callback. This workflow reads
accepted candidate bindings and journals the existing comparison decision; it
never downloads assets, accepts replacements or owns the caller's resources.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from verboisy.core.fitness import compare_candidate_fitness, semantics_for_pointer, temporal_errors
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.extractor.descriptor_projection import grounded_projected_descriptors
from verboisy.extractor.unit_projection import grounded_projected_units

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def compare_dataset_evidence(
    runner: ResearchRunner,
    page: Snapshot,
    candidate: Candidate,
    verify_candidate: Callable[[Candidate, Snapshot, dict[str, Any], TaskSpec], list[str]],
) -> str | None:
    """Apply explicit latest policy to declared identities without dropping metadata."""
    context = runner.store.accepted_candidate_context(runner.rid, candidate, runner.task)
    if context is None:
        return None
    old, snapshot_id = context
    old_page = runner.store.load_snapshot(runner.rid, snapshot_id)
    if old_page is None or verify_candidate(old, old_page, runner.schema, runner.task):
        return "old"
    semantics = {
        pointer: replace(field, temporal_intent=runner.temporal_intent)
        if field.temporal_intent is None
        and field.reference_period == "required"
        and field.temporal_class in {"mutable", "slow_changing"}
        else field
        for pointer, field in runner.field_semantics.items()
    }
    comparison = compare_candidate_fitness(old, candidate, semantics)
    blocked_reason = None
    repair = False
    if comparison.preference in {"new", "same"}:
        preserved = all(
            pointer in candidate.temporal_evidence
            and (
                pointer in comparison.newer_fields
                or proof.reference_year == candidate.temporal_evidence[pointer].reference_year
            )
            for pointer, proof in old.temporal_evidence.items()
        )
        old_units = grounded_projected_units(old, old_page)
        new_units = grounded_projected_units(candidate, page)
        preserved = preserved and all(
            pointer in new_units and unit.canonical_unit == new_units[pointer].canonical_unit
            for pointer, unit in old_units.items()
        )
        old_descriptors = grounded_projected_descriptors(old, old_page)
        new_descriptors = grounded_projected_descriptors(candidate, page)
        preserved = preserved and all(
            pointer in new_descriptors
            and kind in new_descriptors[pointer]
            and descriptor.observed_label == new_descriptors[pointer][kind].observed_label
            for pointer, bindings in old_descriptors.items()
            for kind, descriptor in bindings.items()
        )
        if comparison.preference == "same" and preserved:
            repaired = []
            year_repair = False
            for pointer in sorted(
                set(new_units) | set(new_descriptors) | set(candidate.temporal_evidence)
            ):
                field = semantics_for_pointer(runner.field_semantics, pointer)
                if field is None:
                    continue
                if (
                    field.reference_period == "required"
                    and field.comparable_across_rows
                    and field.temporal_class != "static"
                    and pointer in candidate.temporal_evidence
                    and pointer not in old.temporal_evidence
                ):
                    repaired.append(pointer + ":reference_year")
                    year_repair = True
                if field.unit_sensitive and pointer in new_units and pointer not in old_units:
                    repaired.append(pointer + ":unit")
                for kind in ("definition", "methodology"):
                    if (
                        getattr(field, kind + "_sensitive")
                        and kind in new_descriptors.get(pointer, {})
                        and kind not in old_descriptors.get(pointer, {})
                    ):
                        repaired.append(pointer + ":" + kind)
            if (
                repaired
                and json.dumps(old.record, sort_keys=True, allow_nan=False)
                == json.dumps(candidate.record, sort_keys=True, allow_nan=False)
                and not verify_candidate(candidate, page, runner.schema, runner.task)
                and (
                    not year_repair
                    or not temporal_errors(
                        candidate,
                        page,
                        runner.schema,
                        runner.temporal_intent,
                        current_year=runner.current_year,
                        field_semantics=runner.field_semantics,
                    )
                )
            ):
                comparison = replace(comparison, preference="new")
                repair = True
        if not preserved and comparison.preference == "new":
            comparison = replace(comparison, preference="old")
            blocked_reason = "metadata_regression"
    runner.store.event(
        runner.rid,
        "candidate_comparison",
        {
            "url": page.url,
            "comparison_mode": "dataset_metadata_repair" if repair else "dataset_temporal",
            "blocked_reason": blocked_reason,
            **comparison.as_event(),
        },
    )
    return comparison.preference
