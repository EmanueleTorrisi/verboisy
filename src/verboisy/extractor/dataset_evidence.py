# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic snapshots and proofs for immutable captured dataset rows."""

from __future__ import annotations

import json
import uuid

from verboisy.evidence.models import (
    Candidate,
    ProjectionPlan,
    Proof,
    Snapshot,
    Source,
    TemporalProof,
)
from verboisy.evidence.verify import leaves
from verboisy.extractor.dataset import SourceRow
from verboisy.extractor.projection import project_row
from verboisy.storage.assets import StoredDatasetAsset


def _row_scope(asset: StoredDatasetAsset, row: SourceRow, plan: ProjectionPlan | None) -> str:
    suffix = "" if plan is None else ":" + json.dumps(plan.model_dump(), sort_keys=True)
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"verboisy:dataset-row:{asset.id}:{row.row_index}{suffix}"
    ).hex


def row_evidence(
    asset: StoredDatasetAsset, row: SourceRow, plan: ProjectionPlan | None = None
) -> tuple[Snapshot, Candidate]:
    """Capture each exact JSON leaf under its immutable asset row scope."""
    scope = _row_scope(asset, row, plan)
    values = row.values
    sources = []
    evidence = {}
    temporal_evidence = {}
    for pointer, value in leaves(values).items():
        quote = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        sources.append(Source(id=pointer, kind="text", text=quote, scope=scope))
        evidence[pointer] = Proof(source=pointer, quote=quote, transform="dataset")
    if plan is not None:
        projected = project_row(row, plan)
        values = projected.values
        evidence = {}
        for derivation in projected.derivations:
            year = derivation.temporal_derivation
            if year is not None:
                temporal_evidence[derivation.output_pointer] = TemporalProof(
                    source=year["year_pointer"],
                    quote=year["observed_year_json"],
                    reference_year=year["reference_year"],
                )
            for pointer in leaves(values):
                target = derivation.output_pointer
                if pointer == target or pointer.startswith(target + "/"):
                    source_pointer = derivation.source_pointer + pointer[len(target) :]
                    source = next(item for item in sources if item.id == source_pointer)
                    evidence[pointer] = Proof(
                        source=source_pointer, quote=source.text, transform="dataset_projection"
                    )
    return (
        Snapshot(
            id=scope,
            url=asset.download.final_url,
            fetched_at=asset.acquired_at,
            content_hash=asset.download.dataset.sha256,
            sources=sources,
            truncated=False,
            dataset_asset_id=asset.id,
            dataset_row_index=row.row_index,
            dataset_projection=plan,
            dataset_source_row_json=row.values_json if plan is not None else None,
        ),
        Candidate(
            scope=scope, record=values, evidence=evidence, temporal_evidence=temporal_evidence
        ),
    )
