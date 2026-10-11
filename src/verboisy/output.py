# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepare and publish export views after the research contract has been evaluated.

This module shapes accepted records and delegates file writing to storage. It never
starts research, decides proposals, or changes the ledger's accepted evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verboisy.evidence.models import TaskSpec
from verboisy.presentation import present_rows
from verboisy.presentation_config import PresentationPreferences
from verboisy.product import (
    SortKey,
    apply_smart_ids,
    assign_row_ids,
    load_rows,
    relation_field,
    transform_rows,
)
from verboisy.research_summary import summarize_fields
from verboisy.storage.dataset import export_dataset
from verboisy.storage.numeric_presentation import output_numeric_units
from verboisy.storage.proof import export_proof
from verboisy.storage.research import ResearchStore
from verboisy.time_series import inspect_time_series, validate_time_series
from verboisy.utils.exceptions import VerboisyError


@dataclass(frozen=True)
class PreparedOutput:
    """One shaped generation and the evidence mapping required to publish it."""

    rows: list[dict[str, Any]]
    notices: list[str]
    metadata: dict[str, Any]
    output_lineage: list[dict[str, Any]]
    public_ids: dict[str, int]
    smartid_decisions: list[dict[str, Any]]


@dataclass(frozen=True)
class OutputArtifacts:
    """Paths produced by successful publication; evidence remains in the ledger."""

    manifests: tuple[Path, ...]
    proof_path: Path | None


def prepare_output(
    store: ResearchStore,
    rid: str,
    target_schema: dict[str, Any],
    spec: TaskSpec,
    display: PresentationPreferences,
    *,
    schema_fields: list[str],
    strings: bool,
    groupby: str | None,
    sort_keys: list[SortKey],
    smartid: str | Path | None,
    schema_inferred: bool,
    change_notice: str | None,
) -> PreparedOutput:
    """Shape and identify accepted values before applying any display conversion.

    Public row IDs are assigned only after grouping and sorting. The internal
    contributor mapping is captured first so exported cells keep their evidence.
    """
    rows = store.records(rid)
    coverage, semantic_notices = summarize_fields(rows, schema_fields)
    time_series = None
    validate_time_series(
        spec.time_series, schema_fields, groupby, bool(sort_keys), spec.identity_fields
    )
    if spec.time_series is not None:
        rows, time_series, series_notices = inspect_time_series(rows, spec.time_series)
        semantic_notices.extend(series_notices)
    transformed = transform_rows(
        rows,
        schema_fields=schema_fields,
        strings=strings,
        groupby=groupby,
        sort_keys=sort_keys,
    )
    transformed.notices.extend(semantic_notices)
    if change_notice is not None:
        transformed.notices.insert(0, change_notice)

    public_ids = {
        str(row.get("id")): index
        for index, row in enumerate(
            transformed.rows,
            start=1,
        )
        if row.get("id") is not None
    }

    output_lineage = (
        [
            {"output_id": index, "record_id": str(row["id"])}
            for index, row in enumerate(transformed.rows, start=1)
        ]
        if groupby is None
        else [
            {"output_id": index, "record_ids": transformed.contributors[str(row["id"])]}
            for index, row in enumerate(transformed.rows, start=1)
        ]
    )
    transformed.rows = assign_row_ids(transformed.rows)

    smartid_decisions: list[dict[str, Any]] = []
    relation_name: str | None = None
    if smartid:
        previous = load_rows(smartid)
        relation_name = relation_field(smartid)
        transformed.rows, smartid_decisions = apply_smart_ids(
            transformed.rows, previous, relation_name, identity_fields=spec.identity_fields
        )
        store.event(
            rid,
            "smartid",
            {
                "dataset": str(Path(smartid).resolve()),
                "relation_field": relation_name,
                "decisions": smartid_decisions,
            },
        )

    # Identity matching and dataset shaping operate on accepted values. Apply
    # presentation last so changing display units cannot change record identity.
    display_rows = present_rows(
        transformed.rows,
        target_schema,
        display,
        protected=spec.identity_fields,
        numeric_units=output_numeric_units(store, rid, output_lineage),
    )
    if display_rows != transformed.rows:
        transformed.notices.append(
            "* Display formatting applied; original values remain in the evidence. "
            "Unit conversions round to six decimal places; date-time offsets are preserved."
        )
    transformed.rows = display_rows

    metadata = {
        "field_coverage": coverage,
        "time_series": time_series,
        "presentation_preferences": display.model_dump(),
        "schema_inferred": schema_inferred,
        "string_mode": strings,
        "grouping": transformed.group_plan.__dict__ if transformed.group_plan else None,
        "ordering": [key.__dict__ for key in transformed.applied_sort],
        "notices": transformed.notices,
        "smartid_relation": relation_name,
    }
    return PreparedOutput(
        rows=transformed.rows,
        notices=transformed.notices,
        metadata=metadata,
        output_lineage=output_lineage,
        public_ids=public_ids,
        smartid_decisions=smartid_decisions,
    )


def write_output(
    store: ResearchStore,
    rid: str,
    prepared: PreparedOutput,
    destinations: tuple[Path, ...],
    target_schema: dict[str, Any],
    spec: TaskSpec,
    display: PresentationPreferences,
    *,
    proof: bool,
    dataset_consistency: dict[str, Any] | None,
) -> OutputArtifacts:
    """Publish each destination, retaining the existing per-file atomic boundaries.

    Multiple destinations are not one filesystem transaction. A later failure can
    leave an earlier valid generation; the saved ledger permits a complete retry.
    """
    manifests: list[Path] = []
    proof_path: Path | None = None
    for destination in destinations:
        try:
            manifests.append(
                export_dataset(
                    store,
                    rid,
                    destination,
                    target_schema,
                    spec,
                    rows=prepared.rows,
                    metadata=prepared.metadata,
                    output_lineage=prepared.output_lineage,
                    dataset_consistency=dataset_consistency,
                    presentation=display,
                )
            )
        except (OSError, ValueError):
            raise VerboisyError(
                f"Export failed; run {rid} is saved. Resume with a writable destination"
            ) from None
    if proof:
        if not destinations:
            raise VerboisyError("--proof requires at least one --export destination")
        proof_path = export_proof(
            store,
            rid,
            destinations[0],
            notices=prepared.notices,
            smartid_decisions=prepared.smartid_decisions,
            public_ids=prepared.public_ids,
            output_lineage=prepared.output_lineage,
        )
    return OutputArtifacts(tuple(manifests), proof_path)
