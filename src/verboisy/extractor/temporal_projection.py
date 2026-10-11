# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reference years grounded in explicitly selected captured row columns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from verboisy.evidence.models import Candidate, Snapshot
from verboisy.extractor.dataset import DatasetParseError, SourceRow, parse_dataset
from verboisy.extractor.projection import ProjectionError, _encode, _lookup, _parts, project_row


@dataclass(frozen=True)
class TemporalProjection:
    row_index: int
    source_pointer: str | None
    line_start: int | None
    line_end: int | None
    value_pointer: str
    year_pointer: str
    source_value_json: str
    observed_year_json: str
    reference_year: int
    policy_version: str = "1"

    @property
    def value(self) -> Any:
        """Return the original typed field value without changing it."""
        return json.loads(self.source_value_json)


def project_reference_year(
    row: SourceRow, value_pointer: str, year_pointer: str
) -> TemporalProjection:
    """Associate a captured field with an explicit same-row reference-year column.

    Accept an integer or exactly four ASCII decimal digits in 1000..9999.
    Dates, ranges, decimals, publication text and missing years are not inferred.
    """
    value_parts, year_parts = _parts(value_pointer), _parts(year_pointer)
    if len(value_parts) > 32 or len(year_parts) > 32:
        raise ProjectionError("Reference-year projection pointer depth exceeded")
    values = row.values
    value, observed = _lookup(values, value_parts), _lookup(values, year_parts)
    if isinstance(observed, int) and not isinstance(observed, bool):
        year = observed
    elif isinstance(observed, str) and re.fullmatch(r"[1-9][0-9]{3}", observed):
        year = int(observed)
    else:
        raise ProjectionError("Reference year requires an integer or four ASCII digits")
    if not 1000 <= year <= 9999:
        raise ProjectionError("Reference year must be in 1000..9999")
    return TemporalProjection(
        row.row_index,
        row.source_pointer,
        row.line_start,
        row.line_end,
        value_pointer,
        year_pointer,
        _encode(value),
        _encode(observed),
        year,
    )


def grounded_projected_years(candidate: Candidate, page: Snapshot) -> dict[str, TemporalProjection]:
    """Replay year bindings and require exact auxiliary sources and temporal proofs."""
    plan = page.dataset_projection
    if plan is None or not any(
        getattr(field, "reference_year_source", None) for field in plan.fields
    ):
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
            year_source = getattr(field, "reference_year_source", None)
            if year_source is None:
                continue
            year = project_reference_year(raw, field.source, year_source)
            source = sources.get(year_source)
            proof = candidate.temporal_evidence.get(field.target)
            if (
                source is None
                or source.kind != "text"
                or source.scope != candidate.scope
                or source.text != year.observed_year_json
                or proof is None
                or proof.source != year_source
                or proof.quote != year.observed_year_json
                or proof.reference_year != year.reference_year
            ):
                return {}
            result[field.target] = year
        return result
    except (ProjectionError, DatasetParseError, ValueError, TypeError, IndexError, UnicodeError):
        return {}
