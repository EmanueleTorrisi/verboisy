# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Presentation preferences never change accepted evidence or research requirements.

Conversions require explicit unit-bearing strings or verified numeric unit bindings.
Values without unit context remain untouched. Date formatting accepts ISO source values only, so
locale preferences cannot reinterpret an ambiguous date encountered on a website.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from verboisy.extractor.schema_paths import SchemaPathIndex

# Keep these imports public for integrations using the original presentation module.
from verboisy.presentation_config import (
    PresentationPreferences as PresentationPreferences,
)
from verboisy.presentation_config import (
    preferences as preferences,
)

# Factors are defined relative to kilograms and metres; pound and foot are exact.
_UNITS = {
    **{u: ("mass", Decimal("1")) for u in ("kg", "kilogram", "kilograms")},
    **{u: ("mass", Decimal("0.001")) for u in ("g", "gram", "grams")},
    **{u: ("mass", Decimal("0.45359237")) for u in ("lb", "lbs", "pound", "pounds")},
    **{u: ("length", Decimal("1")) for u in ("m", "meter", "meters", "metre", "metres")},
    "cm": ("length", Decimal("0.01")),
    "mm": ("length", Decimal("0.001")),
    **{
        u: ("length", Decimal("1000"))
        for u in ("km", "kilometer", "kilometers", "kilometre", "kilometres")
    },
    **{u: ("length", Decimal("0.3048")) for u in ("ft", "foot", "feet")},
    **{u: ("length", Decimal("0.0254")) for u in ("in", "inch", "inches")},
}
_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_QUANTITY = re.compile(
    rf"(?P<low>{_NUMBER})\s*(?P<left>[A-Za-z]+)?"
    rf"(?:\s*(?:[-\u2013\u2014]|\bto\b)\s*(?P<high>{_NUMBER})\s*(?P<right>[A-Za-z]+))?"
)


def field_schema(schema: dict[str, Any], pointer: str) -> dict[str, Any]:
    return SchemaPathIndex.build(schema).field(pointer) or {}


def present_value(value: Any, field: dict[str, Any], prefs: PresentationPreferences) -> Any:
    """Format a scalar conservatively; six decimal places bound conversion rounding."""
    if not isinstance(value, str) or len(value) > 200:
        return value
    kind = field.get("format")
    if kind in {"date", "date-time"}:
        if prefs.date_format in {"source", "iso"}:
            return value
        try:
            if kind == "date":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    return value
                parsed = date.fromisoformat(value)
                suffix = ""
            else:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})", value):
                    return value
                parsed = datetime.fromisoformat(value).date()
                suffix = " " + value.split("T", 1)[1]
        except ValueError:
            return value
        date_parts = (
            (parsed.day, parsed.month) if prefs.date_format == "dmy" else (parsed.month, parsed.day)
        )
        return f"{date_parts[0]:02}/{date_parts[1]:02}/{parsed.year:04}" + suffix
    # Known formats such as identifiers and URLs are not measurements.
    if kind is not None:
        return value
    match = _QUANTITY.fullmatch(value.strip())
    if match is None:
        return value
    left, right = match["left"], match["right"]
    label = (right or left or "").lower()
    unit = _UNITS.get(label)
    if unit is None or left and right and _UNITS.get(left.lower()) != unit:
        return value
    # "m" and "in" have non-measurement meanings; require an explicit dimension.
    if label in {"m", "in"} and field.get("x-verboisy-dimension") != "length":
        return value
    dimension, factor = unit
    target = prefs.mass_unit if dimension == "mass" else prefs.length_unit
    if target == "source" or label == target:
        return value
    try:
        with localcontext() as context:
            context.prec = 40
            numbers = [Decimal(match["low"].replace(",", ""))]
            if match["high"] is not None:
                numbers.append(Decimal(match["high"].replace(",", "")))
                if numbers[0] >= numbers[1]:
                    return value
            converted = [n * factor / _UNITS[target][1] for n in numbers]
            parts = [
                format(n.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")
                for n in converted
            ]
    except InvalidOperation:
        return value
    return " - ".join("0" if part == "-0" else part for part in parts) + " " + target


def present_rows(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    prefs: PresentationPreferences,
    *,
    protected: list[str],
    numeric_units: dict[tuple[Any, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Work on copies, preserving public identifiers and caller-declared identity fields."""

    index = SchemaPathIndex.build(schema)

    def walk(value: Any, pointer: str, output_id: Any) -> Any:
        if pointer == "/id" or any(pointer == p or pointer.startswith(p + "/") for p in protected):
            return value
        if isinstance(value, dict):
            return {
                k: walk(v, pointer + "/" + k.replace("~", "~0").replace("/", "~1"), output_id)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v, pointer + f"/{i}", output_id) for i, v in enumerate(value)]
        binding = (numeric_units or {}).get((output_id, pointer))
        if binding is not None:
            return present_number(value, binding["label"], prefs)
        return present_value(value, index.field(pointer) or {}, prefs)

    return [walk(copy.deepcopy(row), "", row.get("id")) for row in rows]


def present_number(value: Any, label: str, prefs: PresentationPreferences) -> Any:
    """Convert a bound cell, retaining numeric and string-mode column types."""
    conversion = number_conversion(value, label, prefs)
    return conversion["output"] if conversion is not None else value


def number_conversion(
    value: Any, label: str, prefs: PresentationPreferences
) -> dict[str, Any] | None:
    """Return a replayable display step only when finite arithmetic succeeds.

    A failed conversion must not label an unchanged number with the requested unit.
    Zero still receives a step, since equal numeric values need not have equal units.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    label = " ".join(label.casefold().strip().rstrip(".").split())
    unit = _UNITS.get(label)
    target = numeric_display_unit(label, prefs)
    if unit is None or target is None or len(str(value)) > 200:
        return None
    try:
        with localcontext() as context:
            context.prec = 240
            number = Decimal(str(value))
            if not number.is_finite():
                return None
            converted = (number * unit[1] / _UNITS[target][1]).quantize(Decimal("0.000001"))
            text = format(converted, "f").rstrip("0").rstrip(".")
            text = "0" if text == "-0" else text
            output = (
                value
                if unit[1] == _UNITS[target][1]
                else text
                if isinstance(value, str)
                else int(converted)
                if converted == converted.to_integral()
                else float(converted)
            )
            # JSON floats must still represent the rounded decimal result. Large
            # fractional quantities can lose digits even after decimal rounding.
            if isinstance(output, float) and Decimal(str(output)) != converted:
                return None
    except InvalidOperation:
        return None
    return {
        "output": output,
        "source_unit": label,
        "target_unit": target,
        "decimal_places": 6,
        "rounding": "half_even",
        "policy_version": "1",
    }


def numeric_display_unit(label: str, prefs: PresentationPreferences) -> str | None:
    """Name a supported target unit without inferring a measurement dimension."""
    unit = _UNITS.get(" ".join(label.casefold().strip().rstrip(".").split()))
    if unit is None:
        return None
    target = prefs.mass_unit if unit[0] == "mass" else prefs.length_unit
    return None if target == "source" else target
