# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Order explicit observations without inventing timestamps or filling gaps.

Calendar dates and elapsed-time instants have different semantics. A timezone
may resolve a naive instant only when its local clock reading is unambiguous.
Diagnostics describe accepted observations, never the universe being researched.
"""

import json
import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from verboisy.time_series_contract import TimeSeriesSpec as TimeSeriesSpec
from verboisy.utils.exceptions import VerboisyError

_DAY = 86_400_000_000
# Validate clock fields before parsing: newer Python versions accept and normalize
# 24:00:00. The research contract retains invalid observations without interpreting them.
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?"
)


def validate_time_series(
    spec: TimeSeriesSpec | None,
    fields: list[str],
    groupby: str | None,
    ordered: bool,
    identity_fields: list[str] | None = None,
) -> None:
    """Reject incompatible shaping before any acquisition or provider request."""
    if spec is None:
        return
    try:
        spec.validate_identity(identity_fields or [])
    except ValueError as error:
        raise VerboisyError(str(error)) from None
    if not {spec.timestamp_field, *spec.series_fields} <= set(fields):
        raise VerboisyError("Time-series fields must occur in the output schema")
    if groupby is not None or ordered:
        raise VerboisyError(
            "Time-series ordering cannot be combined with grouping or explicit order"
        )


def timestamp_key(value: Any, spec: TimeSeriesSpec) -> int | None:
    """Return exact microseconds, rejecting locale guesses and ambiguous clocks."""
    if not isinstance(value, str):
        return None
    try:
        if spec.timestamp_kind == "date":
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
                return None
            return date.fromisoformat(value).toordinal() * _DAY
        if _INSTANT.fullmatch(value) is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            if spec.assume_timezone is None:
                return None
            zone = ZoneInfo(spec.assume_timezone)
            possibilities = {
                local.astimezone(UTC)
                for fold in (0, 1)
                if (local := parsed.replace(tzinfo=zone, fold=fold))
                .astimezone(UTC)
                .astimezone(zone)
                .replace(tzinfo=None)
                == parsed
            }
            if len(possibilities) != 1:
                return None
            parsed = possibilities.pop()
        utc = parsed.astimezone(UTC)
        return (
            utc.toordinal() * _DAY
            + (utc.hour * 3600 + utc.minute * 60 + utc.second) * 1_000_000
            + utc.microsecond
        )
    except (ValueError, OverflowError):
        return None


def inspect_time_series(
    rows: list[dict[str, Any]], spec: TimeSeriesSpec
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Stable per-series chronology with bounded diagnostic examples.

    Missing counts use integer arithmetic between observed endpoints. They do not
    allocate missing rows, infer calendar cadence, or claim endpoint coverage.
    Invalid observations stay visible at the end; duplicates remain observations.
    """
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    invalid = []
    examples: list[dict[str, Any]] = []
    counts = {
        "invalid_timestamp": 0,
        "invalid_series": 0,
        "duplicate_instant": 0,
        "missing_observations": 0,
        "off_grid_intervals": 0,
    }
    for row in rows:
        keys = [row.get(name) for name in spec.series_fields]
        if any(value is None or not isinstance(value, str | bool | int | float) for value in keys):
            reason = "invalid_series"
            instant = None
        else:
            instant = timestamp_key(row.get(spec.timestamp_field), spec)
            reason = "invalid_timestamp"
        if instant is None:
            counts[reason] += 1
            invalid.append(row)
            if len(examples) < 20:
                examples.append({"record_id": row.get("id"), "reason": reason})
        else:
            try:
                identity = json.dumps(keys, ensure_ascii=False, allow_nan=False)
            except ValueError:
                raise VerboisyError("Time-series identity contains non-finite values") from None
            groups.setdefault(identity, []).append((instant, row))
    output = []
    step = spec.interval_seconds * 1_000_000 if spec.interval_seconds is not None else None
    for observations in groups.values():
        observations.sort(key=lambda item: item[0])
        previous = None
        for instant, row in observations:
            if previous is not None:
                delta = instant - previous
                if delta == 0:
                    counts["duplicate_instant"] += 1
                elif step is not None:
                    if delta % step:
                        counts["off_grid_intervals"] += 1
                    else:
                        counts["missing_observations"] += delta // step - 1
            previous = instant
            output.append(row)
    output.extend(invalid)
    report = {
        "version": 1,
        "scope": "accepted_records",
        "contract": spec.model_dump(),
        "row_count": len(rows),
        "series_count": len(groups),
        "counts": counts,
        "examples": examples,
        "endpoint_coverage_claimed": False,
        "interpolation_applied": False,
    }
    notices = [
        "* Time-series rows ordered within each series; "
        "original timestamps and offsets are preserved."
    ]
    if any(counts.values()):
        notices.append(
            "* Accepted time-series observations have issues: "
            + ", ".join(f"{key}={value}" for key, value in counts.items() if value)
            + ". No observations were filled or silently discarded; "
            "inspect the manifest time_series report."
        )
    return output, report, notices
