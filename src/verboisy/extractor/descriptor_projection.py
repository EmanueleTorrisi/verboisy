# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal field descriptors grounded in explicitly chosen same-row columns."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Literal

from verboisy.evidence.models import Candidate, Snapshot
from verboisy.extractor.dataset import DatasetParseError, SourceRow, parse_dataset
from verboisy.extractor.projection import ProjectionError, _encode, _lookup, _parts, project_row

DescriptorKind = Literal["definition", "methodology"]


@dataclass(frozen=True)
class DescriptorProjection:
    row_index: int
    source_pointer: str | None
    line_start: int | None
    line_end: int | None
    value_pointer: str
    descriptor_pointer: str
    kind: DescriptorKind
    source_value_json: str
    observed_label: str
    descriptor_value_json: str
    policy_version: str = "1"

    @property
    def value(self) -> Any:
        """Return a fresh copy of the original typed value; no conversion occurs."""
        return json.loads(self.source_value_json)


def project_descriptor(
    row: SourceRow,
    value_pointer: str,
    descriptor_pointer: str,
    *,
    kind: DescriptorKind,
) -> DescriptorProjection:
    """Bind an exact nonblank definition or methodology label to its row value.

    Labels retain case, whitespace, Unicode and punctuation. No equivalence,
    authority or quality assessment is inferred from their presence.
    """
    if kind not in ("definition", "methodology"):
        raise ProjectionError("Unsupported dataset descriptor kind")
    value_parts, descriptor_parts = _parts(value_pointer), _parts(descriptor_pointer)
    if len(value_parts) > 32 or len(descriptor_parts) > 32:
        raise ProjectionError("Descriptor projection pointer depth exceeded")
    values = row.values
    value = _lookup(values, value_parts)
    label = _lookup(values, descriptor_parts)
    if not isinstance(label, str) or not label.strip() or len(label) > 500:
        raise ProjectionError("Descriptor requires a nonblank label of at most 500 characters")
    return DescriptorProjection(
        row.row_index,
        row.source_pointer,
        row.line_start,
        row.line_end,
        value_pointer,
        descriptor_pointer,
        kind,
        _encode(value),
        label,
        _encode(label),
    )


def grounded_projected_descriptors(
    candidate: Candidate, page: Snapshot
) -> dict[str, dict[str, DescriptorProjection]]:
    """Replay declared bindings and require exact auxiliary label sources."""
    plan = page.dataset_projection
    if plan is None or not any(getattr(field, "descriptors", ()) for field in plan.fields):
        return {}
    if (
        page.dataset_asset_id is None
        or page.dataset_row_index is None
        or page.dataset_source_row_json is None
        or candidate.scope != page.id
    ):
        return {}
    try:
        raw = parse_dataset(("[" + page.dataset_source_row_json + "]").encode(), "json").rows[0]
        projected = project_row(raw, plan)
        if json.dumps(candidate.record, sort_keys=True, allow_nan=False) != json.dumps(
            projected.values, sort_keys=True, allow_nan=False
        ):
            return {}
        raw = replace(
            raw,
            row_index=page.dataset_row_index,
            source_pointer=None,
            line_start=None,
            line_end=None,
        )
        sources = {source.id: source for source in page.sources}
        result: dict[str, dict[str, DescriptorProjection]] = {}
        for field in plan.fields:
            for binding in getattr(field, "descriptors", ()):
                descriptor = project_descriptor(
                    raw, field.source, binding.source, kind=binding.kind
                )
                source = sources.get(binding.source)
                if (
                    source is None
                    or source.kind != "text"
                    or source.scope != candidate.scope
                    or source.text != descriptor.descriptor_value_json
                ):
                    return {}
                result.setdefault(field.target, {})[binding.kind] = descriptor
        return result
    except (ProjectionError, DatasetParseError, ValueError, TypeError, IndexError, UnicodeError):
        return {}
