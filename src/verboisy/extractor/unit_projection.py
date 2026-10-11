# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exact base-unit derivations grounded in explicitly chosen captured row columns."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

from verboisy.core.units import CanonicalUnit, canonical_unit, normalize_unit_value
from verboisy.evidence.models import Candidate, Snapshot, UnitProjectionField
from verboisy.extractor.dataset import DatasetParseError, SourceRow, parse_dataset
from verboisy.extractor.projection import (
    ProjectionError,
    _convert,
    _encode,
    _lookup,
    _parts,
    project_row,
)


@dataclass(frozen=True)
class UnitProjection:
    row_index: int
    source_pointer: str | None
    line_start: int | None
    line_end: int | None
    value_pointer: str
    unit_pointer: str
    source_value_json: str
    observed_unit_label: str
    observed_unit: CanonicalUnit
    canonical_unit: CanonicalUnit
    normalized_value_json: str
    policy_version: str = "1"

    @property
    def value(self) -> Any:
        return json.loads(self.normalized_value_json)


def project_unit_value(row: SourceRow, value_pointer: str, unit_pointer: str) -> UnitProjection:
    """Derive one base-unit value; require a complete recognized label in the same row.

    Numeric text uses strict JSON notation. Null remains null with a grounded
    unit label. Unknown units, ambiguous labels, and lossy arithmetic fail.
    """
    value_parts, unit_parts = _parts(value_pointer), _parts(unit_pointer)
    if len(value_parts) > 32 or len(unit_parts) > 32:
        raise ProjectionError("Unit projection pointer depth exceeded")
    values = row.values
    raw = _lookup(values, value_parts)
    label = _lookup(values, unit_parts)
    if not isinstance(label, str) or len(label.encode("utf-8")) > 512:
        raise ProjectionError("Unit projection requires a bounded observed unit label")
    unit = canonical_unit(label)
    if unit is None:
        raise ProjectionError("Unit projection requires a complete recognized unit")
    numeric = raw
    if isinstance(raw, str):
        mode = "integer" if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw) else "number"
        numeric = _convert(raw, mode)
    normalized = None
    if numeric is not None:
        normalized = normalize_unit_value(numeric, unit)
        if normalized is None or (isinstance(normalized, float) and not math.isfinite(normalized)):
            raise ProjectionError("Unit projection requires a finite numeric value")
        if Fraction(str(normalized)) != Fraction(str(numeric)) * unit.multiplier:
            raise ProjectionError("Unit projection would lose precision")
    return UnitProjection(
        row.row_index,
        row.source_pointer,
        row.line_start,
        row.line_end,
        value_pointer,
        unit_pointer,
        _encode(raw),
        label,
        unit,
        CanonicalUnit(unit.dimension, unit.base_unit, 1),
        _encode(normalized),
    )


def grounded_projected_units(candidate: Candidate, page: Snapshot) -> dict[str, UnitProjection]:
    """Replay declared unit conversions and require their auxiliary source labels."""
    plan = page.dataset_projection
    if plan is None or not any(isinstance(field, UnitProjectionField) for field in plan.fields):
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
        result = {}
        for field in plan.fields:
            if not isinstance(field, UnitProjectionField):
                continue
            unit = project_unit_value(raw, field.source, field.unit_source)
            source = sources.get(field.unit_source)
            if (
                source is None
                or source.scope != candidate.scope
                or source.text != _encode(unit.observed_unit_label)
            ):
                return {}
            result[field.target] = unit
        return result
    except (ProjectionError, DatasetParseError, ValueError, TypeError, IndexError, UnicodeError):
        return {}
