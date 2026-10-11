# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit deterministic dataset projection with replayable field derivations."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, DecimalException
from typing import Any

from verboisy.evidence.models import (
    ProjectionPlan,
    UnitProjectionField,
)

# - public exports
from verboisy.extractor.dataset import SourceRow
from verboisy.utils.exceptions import VerboisyError


class ProjectionError(VerboisyError):
    """A declared mapping cannot be applied without ambiguity or value loss."""


@dataclass(frozen=True)
class FieldDerivation:
    source_pointer: str
    output_pointer: str
    conversion: str
    source_value_json: str
    output_value_json: str
    unit_derivation: dict[str, Any] | None = None
    descriptor_derivations: tuple[dict[str, Any], ...] = ()
    temporal_derivation: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProjectedRow:
    row_index: int
    source_pointer: str | None
    line_start: int | None
    line_end: int | None
    values_json: str
    derivations: tuple[FieldDerivation, ...]
    projection_version: str = "1"

    @property
    def values(self) -> dict[str, Any]:
        return dict(json.loads(self.values_json))


def _parts(pointer: str) -> list[str]:
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ProjectionError("Invalid JSON pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _lookup(value: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            index = int(part)
            if index >= len(value):
                raise ProjectionError("Source pointer is missing")
            value = value[index]
        else:
            raise ProjectionError("Source pointer is missing")
    return value


def _convert(value: Any, mode: str) -> Any:
    if value is None or mode == "identity":
        return value
    if mode in ("date_iso", "date_dmy", "date_mdy"):
        pattern = (
            r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
            if mode == "date_iso"
            else r"([0-9]{2})/([0-9]{2})/([0-9]{4})"
        )
        match = re.fullmatch(pattern, value) if isinstance(value, str) else None
        if match is None:
            raise ProjectionError("Date conversion requires the declared exact date notation")
        first, second, third = (int(part) for part in match.groups())
        year, month, day = (
            (first, second, third)
            if mode == "date_iso"
            else (third, second, first)
            if mode == "date_dmy"
            else (third, first, second)
        )
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            raise ProjectionError("Date conversion requires a valid calendar date") from None
    if mode == "string":
        if isinstance(value, dict | list):
            raise ProjectionError("String conversion requires a scalar")
        return value if isinstance(value, str) else _encode(value)
    if mode == "boolean":
        if isinstance(value, bool):
            return value
        if value in ("true", "false"):
            return value == "true"
        raise ProjectionError("Boolean conversion requires true or false")
    if isinstance(value, bool):
        raise ProjectionError("Boolean is not a numeric value")
    if mode == "integer":
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            try:
                return int(value)
            except ValueError:
                raise ProjectionError("Integer conversion exceeds runtime limits") from None
        raise ProjectionError("Integer conversion requires an exact integer")
    if isinstance(value, int | float):
        return value
    if not isinstance(value, str) or not re.fullmatch(
        r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?", value
    ):
        raise ProjectionError("Number conversion requires JSON numeric notation")
    try:
        decimal = Decimal(value)
        number = float(value)
    except (DecimalException, ValueError, OverflowError):
        raise ProjectionError("Number conversion exceeds runtime limits") from None
    if not math.isfinite(number) or Decimal(str(number)) != decimal:
        raise ProjectionError("Number conversion would lose precision or range")
    return number


def _encode(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        encoded.encode("utf-8")
        return encoded
    except (ValueError, TypeError, UnicodeEncodeError, RecursionError):
        raise ProjectionError("Projected value is not finite UTF-8 JSON") from None


def project_row(row: SourceRow, plan: ProjectionPlan) -> ProjectedRow:
    """Project one captured row atomically; never mutate source values or guess mappings.

    Source pointers support objects and canonical array indexes. Target pointers
    create objects only. Nulls remain null for every conversion. Numeric strings
    use strict JSON notation without whitespace, separators or locale guessing.
    """
    targets: list[list[str]] = []
    declarations = []
    for field in plan.fields:
        source, target = _parts(field.source), _parts(field.target)
        if len(source) > 32 or len(target) > 32:
            raise ProjectionError("Projection pointer depth exceeded")
        if any(target[: len(old)] == old or old[: len(target)] == target for old in targets):
            raise ProjectionError("Overlapping output pointers")
        targets.append(target)
        declarations.append((field, source, target))
    original = row.values
    output: dict[str, Any] = {}
    derivations = []
    for field, source, target in declarations:
        raw = _lookup(original, source)
        unit_derivation = None
        if isinstance(field, UnitProjectionField):
            from verboisy.extractor.unit_projection import project_unit_value

            converted = project_unit_value(row, field.source, field.unit_source)
            result = converted.value
            unit_derivation = asdict(converted)
        else:
            result = _convert(raw, field.conversion)
        descriptors = getattr(field, "descriptors", ())
        if descriptors and (
            isinstance(result, dict | list)
            or len({binding.kind for binding in descriptors}) != len(descriptors)
        ):
            raise ProjectionError("Descriptors require a scalar target and unique kinds")
        from verboisy.extractor.descriptor_projection import project_descriptor

        descriptor_derivations = tuple(
            asdict(project_descriptor(row, field.source, binding.source, kind=binding.kind))
            for binding in descriptors
        )
        raw_json, result_json = _encode(raw), _encode(result)
        temporal_derivation = None
        year_source = getattr(field, "reference_year_source", None)
        if year_source is not None:
            if isinstance(result, dict | list):
                raise ProjectionError("Reference-year bindings require a scalar target")
            from verboisy.extractor.temporal_projection import project_reference_year

            temporal_derivation = asdict(project_reference_year(row, field.source, year_source))
        parent = output
        for part in target[:-1]:
            parent = parent.setdefault(part, {})
        parent[target[-1]] = result
        derivations.append(
            FieldDerivation(
                field.source,
                field.target,
                field.conversion,
                raw_json,
                result_json,
                unit_derivation,
                descriptor_derivations,
                temporal_derivation,
            )
        )
    return ProjectedRow(
        row.row_index,
        row.source_pointer,
        row.line_start,
        row.line_end,
        _encode(output),
        tuple(derivations),
        plan.version,
    )
