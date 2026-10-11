# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Conservative deterministic unit normalization."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from fractions import Fraction
from math import isfinite


@dataclass(frozen=True)
class CanonicalUnit:
    """One deterministically recognized unit identity."""

    dimension: str
    base_unit: str
    multiplier: int = 1

    def as_event(self) -> dict[str, object]:
        return asdict(self)


_UNIT_ALIASES: dict[
    str,
    CanonicalUnit,
] = {
    # Counts of people.
    "person": CanonicalUnit(
        "count",
        "person",
        1,
    ),
    "persons": CanonicalUnit(
        "count",
        "person",
        1,
    ),
    "people": CanonicalUnit(
        "count",
        "person",
        1,
    ),
    "individual": CanonicalUnit(
        "count",
        "person",
        1,
    ),
    "individuals": CanonicalUnit(
        "count",
        "person",
        1,
    ),
    "thousand persons": CanonicalUnit(
        "count",
        "person",
        1_000,
    ),
    "thousand people": CanonicalUnit(
        "count",
        "person",
        1_000,
    ),
    "thousands of persons": CanonicalUnit(
        "count",
        "person",
        1_000,
    ),
    "thousands of people": CanonicalUnit(
        "count",
        "person",
        1_000,
    ),
    "million persons": CanonicalUnit(
        "count",
        "person",
        1_000_000,
    ),
    "million people": CanonicalUnit(
        "count",
        "person",
        1_000_000,
    ),
    "millions of persons": CanonicalUnit(
        "count",
        "person",
        1_000_000,
    ),
    "millions of people": CanonicalUnit(
        "count",
        "person",
        1_000_000,
    ),
    "billion persons": CanonicalUnit(
        "count",
        "person",
        1_000_000_000,
    ),
    "billion people": CanonicalUnit(
        "count",
        "person",
        1_000_000_000,
    ),
    "billions of persons": CanonicalUnit(
        "count",
        "person",
        1_000_000_000,
    ),
    "billions of people": CanonicalUnit(
        "count",
        "person",
        1_000_000_000,
    ),
    # Mass. Gram is the deterministic base.
    "g": CanonicalUnit(
        "mass",
        "gram",
        1,
    ),
    "gram": CanonicalUnit(
        "mass",
        "gram",
        1,
    ),
    "grams": CanonicalUnit(
        "mass",
        "gram",
        1,
    ),
    "kg": CanonicalUnit(
        "mass",
        "gram",
        1_000,
    ),
    "kilogram": CanonicalUnit(
        "mass",
        "gram",
        1_000,
    ),
    "kilograms": CanonicalUnit(
        "mass",
        "gram",
        1_000,
    ),
    # Length. Avoid ambiguous abbreviations such as "m".
    "meter": CanonicalUnit(
        "length",
        "meter",
        1,
    ),
    "meters": CanonicalUnit(
        "length",
        "meter",
        1,
    ),
    "metre": CanonicalUnit(
        "length",
        "meter",
        1,
    ),
    "metres": CanonicalUnit(
        "length",
        "meter",
        1,
    ),
    "kilometer": CanonicalUnit(
        "length",
        "meter",
        1_000,
    ),
    "kilometers": CanonicalUnit(
        "length",
        "meter",
        1_000,
    ),
    "kilometre": CanonicalUnit(
        "length",
        "meter",
        1_000,
    ),
    "kilometres": CanonicalUnit(
        "length",
        "meter",
        1_000,
    ),
}


def _normalize_unit_label(
    label: str,
) -> str:
    """Normalize presentation only, never infer semantics."""

    return " ".join(label.casefold().strip().rstrip(".").split())


def canonical_unit(
    label: str,
) -> CanonicalUnit | None:
    """Return a unit only for conservatively recognized labels."""

    return _UNIT_ALIASES.get(_normalize_unit_label(label))


def normalize_unit_value(
    value: object,
    unit: CanonicalUnit,
) -> int | float | None:
    """Scale finite JSON numbers without rounding integer arithmetic."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, int):
        return value * unit.multiplier
    if not isfinite(value):
        return None

    normalized = Fraction(str(value)) * unit.multiplier
    if normalized.denominator == 1:
        return normalized.numerator
    try:
        return float(normalized)
    except OverflowError:
        return None


UNIT_NORMALIZATION_EVENT_VERSION = 2
LEGACY_UNIT_NORMALIZATION_EVENT_VERSION = 1


def canonical_unit_from_event(
    value: object,
) -> CanonicalUnit | None:
    """Decode a canonical unit from trusted-shaped persisted data."""

    if not isinstance(value, dict):
        return None

    dimension = value.get("dimension")
    base_unit = value.get("base_unit")
    multiplier = value.get("multiplier")

    if not isinstance(dimension, str):
        return None

    if not isinstance(base_unit, str):
        return None

    if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 0:
        return None

    return CanonicalUnit(
        dimension=dimension,
        base_unit=base_unit,
        multiplier=multiplier,
    )


def unit_normalization_event(
    *,
    record_id: str,
    pointer: str,
    original_value: object,
    unit: CanonicalUnit,
    source_unit: object = None,
    candidate_key: str | None = None,
    snapshot_id: str | None = None,
) -> dict[str, object] | None:
    """Encode a bound transformation, or a legacy event for old callers."""

    binding_supplied = candidate_key is not None or snapshot_id is not None
    if binding_supplied and (not candidate_key or not snapshot_id):
        raise ValueError("Normalization requires both candidate_key and snapshot_id")

    normalized = normalize_unit_value(
        original_value,
        unit,
    )

    if normalized is None:
        return None

    event: dict[str, object] = {
        "version": (
            UNIT_NORMALIZATION_EVENT_VERSION
            if binding_supplied
            else LEGACY_UNIT_NORMALIZATION_EVENT_VERSION
        ),
        "record_id": record_id,
        "pointer": pointer,
        "original_value": original_value,
        "normalized_value": normalized,
        "observed_unit": unit.as_event(),
        "canonical_unit": CanonicalUnit(
            dimension=unit.dimension,
            base_unit=unit.base_unit,
            multiplier=1,
        ).as_event(),
        "multiplier": unit.multiplier,
    }

    if binding_supplied:
        event["candidate_key"] = candidate_key
        event["snapshot_id"] = snapshot_id

    if isinstance(source_unit, dict):
        event["source_unit"] = source_unit

    return event


def normalized_unit_value_from_events(
    events: list[dict[str, object]],
    *,
    record_id: str,
    pointer: str,
    original_value: object,
    unit: CanonicalUnit,
    candidate_key: str | None = None,
    snapshot_id: str | None = None,
) -> int | float | None:
    """Replay against caller-grounded units and immutable candidate values.

    Version 1 is revalidated using the current source context. Version 2 also
    requires an exact candidate and snapshot binding. The newest valid event
    wins; malformed or stale later events cannot hide a valid earlier event.
    """

    expected = normalize_unit_value(original_value, unit)
    if expected is None:
        return None

    canonical = CanonicalUnit(unit.dimension, unit.base_unit, 1)
    for event in reversed(events):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        version = payload.get("version")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version
            not in (
                LEGACY_UNIT_NORMALIZATION_EVENT_VERSION,
                UNIT_NORMALIZATION_EVENT_VERSION,
            )
        ):
            continue
        if version == LEGACY_UNIT_NORMALIZATION_EVENT_VERSION and (
            "candidate_key" in payload or "snapshot_id" in payload
        ):
            continue
        if version == UNIT_NORMALIZATION_EVENT_VERSION and (
            not candidate_key
            or not snapshot_id
            or payload.get("candidate_key") != candidate_key
            or payload.get("snapshot_id") != snapshot_id
        ):
            continue
        if (
            payload.get("record_id") != record_id
            or payload.get("pointer") != pointer
            or type(payload.get("original_value")) is not type(original_value)
            or payload.get("original_value") != original_value
            or canonical_unit_from_event(payload.get("observed_unit")) != unit
            or canonical_unit_from_event(payload.get("canonical_unit")) != canonical
            or isinstance(payload.get("multiplier"), bool)
            or not isinstance(payload.get("multiplier"), int)
            or payload.get("multiplier") != unit.multiplier
            or type(payload.get("normalized_value")) is not type(expected)
            or payload.get("normalized_value") != expected
        ):
            continue
        return expected
    return None


def unit_label_is_complete(label: str, quote: str, observed: str) -> bool:
    """Reject partial known units, including scales outside a shortened quote.

    Multiple possible occurrences are treated conservatively: any enclosing
    recognized unit expression makes a shorter proposed label ambiguous.
    Unknown complete labels remain metadata, never inferred conversions.
    """

    if re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", quote) is None:
        return False

    proposed = _normalize_unit_label(label)
    aliases = "|".join(re.escape(alias) for alias in sorted(_UNIT_ALIASES, key=len, reverse=True))
    pattern = r"(?<!\w)(?:(?:thousands?|millions?|billions?)(?: of)?\s+)?(?:" + aliases + r")(?!\w)"
    for match in re.finditer(pattern, observed, flags=re.IGNORECASE):
        expression = _normalize_unit_label(match.group())
        if proposed != expression and proposed in expression:
            return False
    return True
