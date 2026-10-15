# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cell transformations reconstructed from accepted evidence and validated projections."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from verboisy.core.source_assessment import source_fitness_candidate_key
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.evidence.verify import leaves
from verboisy.extractor.descriptor_projection import (
    grounded_projected_descriptors,
    project_descriptor,
)
from verboisy.extractor.schema_paths import SchemaPathIndex
from verboisy.extractor.temporal_projection import grounded_projected_years, project_reference_year
from verboisy.extractor.unit_projection import grounded_projected_units, project_unit_value
from verboisy.presentation import (
    PresentationPreferences,
    number_conversion,
    present_number,
    present_value,
)
from verboisy.product import GroupPlan, _group_rows, _normalize_row, group_key
from verboisy.storage.assets import StoredDatasetAsset
from verboisy.storage.numeric_presentation import output_numeric_units
from verboisy.storage.research import ResearchStore


def _same(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


@dataclass
class _LineageInputs:
    """Borrowed inputs and lazy replay results owned by one lineage invocation."""

    evidence: dict[str, dict[str, Any]]
    records: list[dict[str, Any]]
    effective: dict[str, dict[str, Any]]
    assets: dict[str, StoredDatasetAsset] = field(default_factory=dict)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    raw_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    projections: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = field(
        default_factory=dict
    )
    candidate_keys: dict[str, str] = field(default_factory=dict)
    retain_replays: bool = True


def build_cell_lineage(
    store: ResearchStore,
    rid: str,
    rows: list[dict[str, Any]],
    mappings: list[dict[str, Any]] | None,
    *,
    strings: bool,
    groupby: str | None = None,
    presentation: PresentationPreferences | None = None,
    schema: dict[str, Any] | None = None,
    protected: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Explain cells from one accepted-ledger view; unsupported derivations stay unresolved.

    Inputs and replay results are reused only within this call. A later export
    reads the ledger again, so new evidence or normalization events stay visible.
    """
    if mappings is None:
        return None
    evidence_rows, records = store.evidence_records(rid)
    evidence = {str(row["record_id"]): row for row in evidence_rows}
    inputs = _LineageInputs(
        evidence,
        records,
        {str(row["id"]): leaves(row) for row in records},
        retain_replays=groupby is not None,
    )
    return _build_cell_lineage(
        store,
        rid,
        rows,
        mappings,
        inputs,
        strings=strings,
        groupby=groupby,
        presentation=presentation,
        schema=schema,
        protected=protected,
    )


def _build_cell_lineage(
    store: ResearchStore,
    rid: str,
    rows: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    context_inputs: _LineageInputs,
    *,
    strings: bool,
    groupby: str | None = None,
    presentation: PresentationPreferences | None = None,
    schema: dict[str, Any] | None = None,
    protected: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Reuse the same inputs for each grouped contributor's scalar derivation."""

    numeric_units = output_numeric_units(store, rid, mappings) if presentation and mappings else {}

    def numeric_binding(output_id: Any, pointer: str, value: Any) -> dict[str, Any] | None:
        if presentation is None or any(
            pointer == p or pointer.startswith(p + "/") for p in protected or []
        ):
            return None
        binding = numeric_units.get((output_id, pointer))
        return (
            binding
            if binding and number_conversion(value, binding["label"], presentation)
            else None
        )

    schema_index = SchemaPathIndex.build(schema or {}) if presentation is not None else None

    def display(value: Any, pointer: str, output_id: Any) -> Any:
        if presentation is None or any(
            pointer == p or pointer.startswith(p + "/") for p in protected or []
        ):
            return value
        binding = numeric_units.get((output_id, pointer))
        if binding:
            return present_number(value, binding["label"], presentation)
        assert schema_index is not None
        return present_value(value, schema_index.field(pointer) or {}, presentation)

    def presentation_step(
        value: Any, formatted: Any, pointer: str, output_id: Any
    ) -> dict[str, Any]:
        step = {
            "operation": "presentation",
            "input": value,
            "output": formatted,
            "preferences": presentation.model_dump() if presentation else None,
        }
        binding = numeric_binding(output_id, pointer, value)
        if binding and presentation:
            step.update(number_conversion(value, binding["label"], presentation) or {})
            step["unit_evidence"] = binding["bindings"]
        return step

    evidence = context_inputs.evidence
    effective = context_inputs.effective
    grouped: dict[tuple[str, ...], tuple[dict[str, Any], GroupPlan]] = {}
    if groupby is not None:
        source_rows = context_inputs.records
        normalized = [_normalize_row(row, list(row), strings=strings) for row in source_rows]
        if normalized:
            group_rows, plan, contributors = _group_rows(normalized, groupby)
            grouped = {tuple(contributors[row["id"]]): (row, plan) for row in group_rows}
    projection_assets = context_inputs.assets
    cells: list[dict[str, Any]] = []
    for row, mapping in zip(rows, mappings, strict=True):
        record_id = mapping.get("record_id")
        for pointer, output_value in leaves(row).items():
            if pointer == "/id":
                continue
            cell: dict[str, Any] = {
                "output_id": mapping["output_id"],
                "pointer": pointer,
                "output_value": output_value,
                "status": "unresolved",
                "steps": [],
            }
            cells.append(cell)
            if record_id is None:
                cell["record_ids"] = mapping["record_ids"]
                match = grouped.get(tuple(mapping["record_ids"]))
                if match is None:
                    continue
                expected, plan = match
                expected_fields = leaves(expected)
                if pointer not in expected_fields or not _same(
                    display(expected_fields[pointer], pointer, mapping["output_id"]), output_value
                ):
                    continue
                field_name = next(
                    key for key in expected if pointer in leaves({key: expected[key]})
                )
                inputs = []
                for contributor in mapping["record_ids"]:
                    if pointer not in effective[contributor]:
                        inputs.append(
                            {
                                "record_id": contributor,
                                "pointer": pointer,
                                "status": "absent",
                                "contribution": "absence",
                            }
                        )
                        continue
                    value = effective[contributor][pointer]
                    if strings:
                        value = _normalize_row({"value": value}, ["value"], strings=True)["value"]
                    # Construct only this cell, preserving each accepted evidence binding.
                    source_cell = _build_cell_lineage(
                        store,
                        rid,
                        [{"id": contributor, field_name: value}],
                        [{"output_id": contributor, "record_id": contributor}],
                        context_inputs,
                        strings=strings,
                    )
                    inputs.append(source_cell[0])
                cell["contributors"] = inputs
                if all(source["status"] in {"resolved", "absent"} for source in inputs):
                    operation = (
                        "group_key" if field_name == plan.field else plan.aggregations[field_name]
                    )
                    cell["steps"] = [
                        {
                            "operation": operation,
                            "inputs": [
                                source["output_value"]
                                for source in inputs
                                if source["status"] != "absent"
                            ],
                            "output": expected_fields[pointer],
                            "null_policy": "typed_presence"
                            if operation == "group_key"
                            else "exclude_unknowns; empty_is_null",
                            "numeric_policy": "exact_integer_sum; rational_average; finite_json",
                            "group_key": group_key(expected, plan.field),
                            "reason": "no_observed_numeric_inputs"
                            if operation != "group_key" and expected_fields[pointer] is None
                            else None,
                        }
                    ]
                    if not _same(expected_fields[pointer], output_value) or numeric_binding(
                        mapping["output_id"], pointer, expected_fields[pointer]
                    ):
                        cell["steps"].append(
                            presentation_step(
                                expected_fields[pointer],
                                output_value,
                                pointer,
                                mapping["output_id"],
                            )
                        )
                    cell["status"] = "resolved"
                continue
            cell["record_id"] = record_id
            context = evidence[record_id]
            if "candidate" not in context or "snapshot" not in context:
                continue
            if record_id not in context_inputs.candidates:
                context_inputs.candidates[record_id] = Candidate.model_validate(
                    context["candidate"]
                )
                context_inputs.raw_fields[record_id] = leaves(
                    context_inputs.candidates[record_id].record
                )
            candidate = context_inputs.candidates[record_id]
            raw_fields = context_inputs.raw_fields[record_id]
            if pointer not in raw_fields:
                continue
            raw = raw_fields[pointer]
            value = effective[record_id][pointer]
            proof = candidate.evidence.get(pointer)
            if proof is not None and proof.transform == "dataset_projection":
                source = next(
                    item for item in context["snapshot"]["sources"] if item["id"] == proof.source
                )
                cell["source_value"] = json.loads(source["text"])
                cell["source_pointer"] = proof.source
                cell["dataset_asset_id"] = context["snapshot"]["dataset_asset_id"]
                cell["dataset_row_index"] = context["snapshot"]["dataset_row_index"]
                cell["steps"].append(
                    {
                        "operation": "dataset_projection",
                        "input": cell["source_value"],
                        "output": raw,
                        "plan": context["snapshot"]["dataset_projection"],
                    }
                )
            if record_id not in context_inputs.projections:
                snapshot = Snapshot.model_validate(context["snapshot"])
                context_inputs.projections[record_id] = (
                    grounded_projected_units(candidate, snapshot),
                    grounded_projected_descriptors(candidate, snapshot),
                    grounded_projected_years(candidate, snapshot),
                )
                context_inputs.candidate_keys[record_id] = source_fitness_candidate_key(candidate)
            projected_units, projected_descriptors, projected_years = context_inputs.projections[
                record_id
            ]
            if (
                pointer in projected_units
                or pointer in projected_descriptors
                or pointer in projected_years
            ):
                asset_id = str(context["snapshot"]["dataset_asset_id"])
                if asset_id not in projection_assets:
                    projection_assets[asset_id] = store.load_dataset_asset(rid, asset_id)
                source_row = projection_assets[asset_id].download.dataset.rows[
                    int(context["snapshot"]["dataset_row_index"]) - 1
                ]
            if pointer in projected_units:
                unit = projected_units[pointer]
                cell["unit_derivation"] = asdict(
                    project_unit_value(source_row, unit.value_pointer, unit.unit_pointer)
                )
            if pointer in projected_descriptors:
                cell["descriptor_derivations"] = [
                    asdict(
                        project_descriptor(
                            source_row,
                            descriptor.value_pointer,
                            descriptor.descriptor_pointer,
                            kind=descriptor.kind,
                        )
                    )
                    for descriptor in projected_descriptors[pointer].values()
                ]
            if pointer in projected_years:
                year = projected_years[pointer]
                cell["temporal_derivation"] = asdict(
                    project_reference_year(source_row, year.value_pointer, year.year_pointer)
                )
            cell["raw_value"] = raw
            cell["snapshot_id"] = context["snapshot"]["id"]
            cell["candidate_key"] = context_inputs.candidate_keys[record_id]
            cell["steps"].append(
                {
                    "operation": "literal_evidence",
                    "value": raw,
                    "proof": context["candidate"]["evidence"].get(pointer),
                }
            )
            if not _same(raw, value):
                # ResearchStore.records only changes accepted values by validated unit replay.
                cell["steps"].append(
                    {"operation": "unit_normalization", "input": raw, "output": value}
                )
            if strings:
                converted = _normalize_row({"value": value}, ["value"], strings=True)["value"]
                cell["steps"].append(
                    {"operation": "string_conversion", "input": value, "output": converted}
                )
                value = converted
            formatted = display(value, pointer, mapping["output_id"])
            if not _same(value, formatted) or numeric_binding(mapping["output_id"], pointer, value):
                cell["steps"].append(
                    presentation_step(value, formatted, pointer, mapping["output_id"])
                )
            if _same(formatted, output_value):
                cell["status"] = "resolved"
        if not context_inputs.retain_replays and record_id is not None:
            # Scalar rows need replay data only while their own cells are built.
            # Grouped contributors revisit records across cells and keep it until
            # this generation ends. Neither path retains models across exports.
            context_inputs.candidates.pop(record_id, None)
            context_inputs.raw_fields.pop(record_id, None)
            context_inputs.projections.pop(record_id, None)
            context_inputs.candidate_keys.pop(record_id, None)
    return cells
