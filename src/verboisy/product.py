# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic product-level contracts for the simplified Verboisy interface."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from verboisy.evidence.verify import lookup
from verboisy.utils.exceptions import VerboisyError

SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True)
class SortKey:
    """One user-supplied ordering key. Sequence order is priority order."""

    field: str
    direction: SortDirection = "asc"

    def __post_init__(self) -> None:
        if not self.field.strip():
            raise VerboisyError("Sort field cannot be empty")
        if self.direction not in ("asc", "desc"):
            raise VerboisyError("Sort direction must be asc or desc")


@dataclass(frozen=True)
class SourcePolicy:
    """Normalized domain policy used for discovery and extraction."""

    include: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    onlyinclude: bool = False

    def __post_init__(self) -> None:
        include = tuple(_normalize_domain(value) for value in self.include)
        avoid = tuple(_normalize_domain(value) for value in self.avoid)
        object.__setattr__(self, "include", tuple(dict.fromkeys(include)))
        object.__setattr__(self, "avoid", tuple(dict.fromkeys(avoid)))
        if self.onlyinclude and not self.include:
            raise VerboisyError("--onlyinclude requires at least one --include domain")

    def permits(self, url: str) -> bool:
        host = _url_host(url)
        if host is None or any(_domain_matches(host, blocked) for blocked in self.avoid):
            return False
        if not self.onlyinclude:
            return True
        return any(_domain_matches(host, allowed) for allowed in self.include)


@dataclass(frozen=True)
class GroupPlan:
    field: str
    aggregations: dict[str, str]
    removed_fields: tuple[str, ...] = ()


@dataclass
class TransformResult:
    rows: list[dict[str, Any]]
    notices: list[str] = field(default_factory=list)
    group_plan: GroupPlan | None = None
    applied_sort: list[SortKey] = field(default_factory=list)
    contributors: dict[str, list[str]] = field(default_factory=dict)


def _normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not value:
        raise VerboisyError("Domain values cannot be empty")
    if "://" in value:
        host = _url_host(value)
        if host is None:
            raise VerboisyError(f"Invalid domain: {value}")
        return host
    if "/" in value or "@" in value or " " in value:
        raise VerboisyError(f"Invalid domain: {value}")
    if not re.fullmatch(r"[a-z0-9.-]+", value) or ".." in value:
        raise VerboisyError(f"Invalid domain: {value}")
    return value


def _url_host(url: str) -> str | None:
    try:
        host = urlsplit(url if "://" in url else f"https://{url}").hostname
    except ValueError:
        return None
    return host.lower().rstrip(".") if host else None


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


_INTEGER_NAMES = {
    "age",
    "quantity",
    "count",
    "employees",
    "rank",
    "year",
    "stock",
}
_NUMERIC_PARTS = {
    "price",
    "cost",
    "amount",
    "weight",
    "height",
    "width",
    "length",
    "rating",
    "revenue",
    "funding",
    "score",
    "percent",
    "percentage",
}
_BOOLEAN_PREFIXES = ("is_", "has_", "can_", "should_")
_BOOLEAN_NAMES = {"active", "available", "enabled", "verified", "in_stock"}
_DATE_NAMES = {"birthdate", "birthday", "date", "founded_date"}
_DATETIME_SUFFIXES = ("_at", "_datetime", "_timestamp")
_URL_NAMES = {"url", "website", "source_url", "homepage", "link"}


def infer_json_type(name: str, sample_values: list[Any] | None = None) -> dict[str, Any]:
    """Infer a conservative JSON Schema field definition from name and samples."""

    key = name.strip().lower()
    samples = [value for value in (sample_values or []) if value is not None and value != ""]
    if samples:
        inferred = _type_from_samples(samples)
        if inferred is not None:
            return inferred
    if key in _INTEGER_NAMES or key.endswith(("_count", "_quantity")):
        return {"type": ["integer", "null"]}
    if key in _DATE_NAMES or key.endswith("_date"):
        return {"type": ["string", "null"], "format": "date"}
    if key.endswith(_DATETIME_SUFFIXES):
        return {"type": ["string", "null"], "format": "date-time"}
    if key in _BOOLEAN_NAMES or key.startswith(_BOOLEAN_PREFIXES):
        return {"type": ["boolean", "null"]}
    if key in _URL_NAMES or key.endswith("_url"):
        return {"type": ["string", "null"], "format": "uri"}
    if any(part in key.split("_") for part in _NUMERIC_PARTS):
        return {"type": ["number", "null"]}
    return {"type": ["string", "null"]}


def _type_from_samples(values: list[Any]) -> dict[str, Any] | None:
    if all(isinstance(value, bool) for value in values):
        return {"type": ["boolean", "null"]}
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return {"type": ["integer", "null"]}
    if all(isinstance(value, int | float) and not isinstance(value, bool) for value in values):
        return {"type": ["number", "null"]}
    if all(isinstance(value, str) for value in values):
        if all(_looks_like_date(value) for value in values):
            return {"type": ["string", "null"], "format": "date"}
        return {"type": ["string", "null"]}
    return None


def _looks_like_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_simple_schema(
    value: str | list[str] | tuple[str, ...], *, strings: bool = False
) -> dict[str, Any]:
    """Compile ``[name,price,...]`` or a field sequence into a collection schema."""

    if isinstance(value, str):
        text = value.strip()
        if not (text.startswith("[") and text.endswith("]")):
            raise VerboisyError("Simple schema must look like [name,price,website]")
        raw = text[1:-1].strip()
        names = [] if not raw else [part.strip().strip("'\"") for part in raw.split(",")]
    else:
        names = [str(item).strip() for item in value]
    if not names or any(not name for name in names):
        raise VerboisyError("Schema must contain at least one nonempty field")
    if len(names) != len(set(names)):
        raise VerboisyError("Schema field names must be unique")
    if "id" in names:
        raise VerboisyError("The id field is generated automatically; remove it from --schema")
    properties = {
        name: ({"type": ["string", "null"]} if strings else infer_json_type(name)) for name in names
    }
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": names,
            "additionalProperties": False,
        },
    }


def load_rows(path: str | Path, *, max_bytes: int = 50_000_000) -> list[dict[str, Any]]:
    """Load an untrusted CSV/JSON dataset with basic shape and size validation."""

    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise VerboisyError(f"Cannot read dataset: {source}") from exc
    if size > max_bytes:
        raise VerboisyError(f"Dataset exceeds {max_bytes} bytes: {source}")
    suffix = source.suffix.lower()
    try:
        if suffix == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise VerboisyError("JSON dataset must be an array of objects")
            rows = payload
        elif suffix == ".csv":
            with source.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or any(not name for name in reader.fieldnames):
                    raise VerboisyError("CSV dataset must have a nonempty header row")
                if len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise VerboisyError("CSV dataset contains duplicate column names")
                rows = [dict(row) for row in reader]
        else:
            raise VerboisyError("Dataset must be CSV or JSON")
    except UnicodeError as exc:
        raise VerboisyError("Dataset is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise VerboisyError("Dataset contains invalid JSON") from exc
    for index, row in enumerate(rows):
        value = row.get("id")

        if isinstance(value, bool) or value is None:
            raise VerboisyError(f"Dataset row {index + 1} is missing a row id")

        if isinstance(value, int):
            if value < 1:
                raise VerboisyError(f"Dataset row {index + 1} has an invalid row id")
            continue

        if isinstance(value, str) and value.strip():
            normalized = value.strip()

            if normalized.isdecimal():
                row["id"] = int(normalized)
            else:
                row["id"] = normalized

            continue

        raise VerboisyError(f"Dataset row {index + 1} is missing a row id")

    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise VerboisyError("Dataset contains duplicate ids")
    return rows


def assign_row_ids(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign one-based integer IDs in final output order."""

    result: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        copy = dict(row)
        copy["id"] = index
        result.append(copy)

    return result


def relation_field(path: str | Path) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "entity"
    irregular = {
        "people": "person",
        "persons": "person",
        "children": "child",
        "men": "man",
        "women": "woman",
    }
    if stem in irregular:
        stem = irregular[stem]
    elif stem.endswith("ies") and len(stem) > 3:
        stem = stem[:-3] + "y"
    elif stem.endswith("sses"):
        stem = stem[:-2]
    elif stem.endswith("s") and not stem.endswith("ss"):
        stem = stem[:-1]
    return f"{stem}_id"


_STRONG_KEYS = (
    "upc",
    "ean",
    "isbn",
    "sku",
    "mpn",
    "manufacturer_part_number",
    "canonical_url",
    "source_url",
    "website",
    "domain",
    "email",
)


def apply_smart_ids(
    rows: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    relation_name: str,
    *,
    identity_fields: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach foreign-key-like IDs only when exact evidence identifies one prior row."""

    if any(relation_name in row for row in rows):
        raise VerboisyError("SmartID relation field already exists in output rows")

    decisions: list[dict[str, Any]] = []
    result: list[dict[str, Any]] = []
    for row in rows:
        matched: list[tuple[dict[str, Any], list[str]]] = []
        for old in previous:
            fields = (
                _matching_declared_identity(row, old, identity_fields)
                if identity_fields
                else _matching_identity_fields(row, old)
            )
            if fields:
                matched.append((old, fields))
        unique_ids = {match[0]["id"] for match in matched}
        linked = next(iter(unique_ids)) if len(unique_ids) == 1 else None
        copy = dict(row)
        copy[relation_name] = linked
        result.append(copy)
        decisions.append(
            {
                "record_id": row.get("id"),
                "relation_field": relation_name,
                "matched_id": linked,
                "matched_fields": sorted({f for _, fields in matched for f in fields}),
                "candidate_ids": sorted(
                    unique_ids, key=lambda value: (type(value).__name__, str(value))
                ),
                "outcome": "exact"
                if linked is not None
                else ("ambiguous" if unique_ids else "unresolved"),
            }
        )
    return result, decisions


def _matching_declared_identity(
    new: dict[str, Any], old: dict[str, Any], pointers: list[str]
) -> list[str]:
    """All declared components must match; never fall back to weaker evidence."""
    for pointer in pointers:
        try:
            left, right = lookup(new, pointer), lookup(old, pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            return []
        if not _same_identifier(left, right):
            return []
    # Retain contradiction vetoes for additional shared strong identifiers.
    for key in _STRONG_KEYS:
        if (
            key in new
            and key in old
            and new[key] not in (None, "")
            and old[key] not in (None, "")
            and not _same_identifier(new[key], old[key])
        ):
            return []
    return list(pointers)


def _matching_identity_fields(new: dict[str, Any], old: dict[str, Any]) -> list[str]:
    strong = [
        key
        for key in _STRONG_KEYS
        if key in new and key in old and new[key] not in (None, "") and old[key] not in (None, "")
    ]
    if any(not _same_identifier(new[key], old[key]) for key in strong):
        return []
    if strong:
        return strong
    # Names alone are insufficient. Require at least one additional exact context field.
    name_keys = [key for key in ("name", "full_name") if _same_field(new, old, key)]
    context_keys = ("surname", "company", "employer", "city", "country", "address", "model")
    shared = [key for key in context_keys if key in new and key in old]
    if any(not _same_nonempty(new[key], old[key]) for key in shared):
        return []
    context = [key for key in shared if _same_nonempty(new[key], old[key])]
    if name_keys and context:
        return name_keys + context
    return []


def _same_identifier(left: Any, right: Any) -> bool:
    """Opaque identifiers and URLs require exact, type-preserving equality."""
    if type(left) is not type(right) or not isinstance(left, str | int) or isinstance(left, bool):
        return False
    if isinstance(left, str) and not left.strip():
        return False
    return bool(left == right)


def _same_field(left: dict[str, Any], right: dict[str, Any], key: str) -> bool:
    return key in left and key in right and _same_nonempty(left[key], right[key])


def _same_nonempty(left: Any, right: Any) -> bool:
    if left is None or right is None or left == "" or right == "":
        return False
    return _normal_identity(left) == _normal_identity(right)


def _normal_identity(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.casefold().split()).rstrip("/")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def transform_rows(
    rows: list[dict[str, Any]],
    *,
    schema_fields: list[str],
    strings: bool = False,
    groupby: str | None = None,
    sort_keys: list[SortKey] | None = None,
) -> TransformResult:
    """Apply deterministic typing, optional grouping, then ordered sorting."""

    normalized = [_normalize_row(row, schema_fields, strings=strings) for row in rows]
    notices: list[str] = []
    group_plan: GroupPlan | None = None
    contributors: dict[str, list[str]] = {}
    if groupby is not None:
        normalized, group_plan, contributors = _group_rows(normalized, groupby)
        notices.append(f"Grouping by {groupby}.")
        if group_plan.removed_fields:
            notices.append(
                "Removed non-aggregable columns: " + ", ".join(group_plan.removed_fields)
            )
    applied: list[SortKey] = []
    available = set(normalized[0]) if normalized else ({groupby} if groupby else set(schema_fields))
    for key in sort_keys or []:
        if key.field in available:
            applied.append(key)
        else:
            notices.append(f"Ignored sort key: {key.field}")
    # Stable sorts in reverse priority preserve the first CLI key as highest priority.
    # Nulls remain last in both directions.
    for key in reversed(applied):
        present = [row for row in normalized if row.get(key.field) is not None]
        missing = [row for row in normalized if row.get(key.field) is None]
        present.sort(
            key=lambda row: _sort_value(row.get(key.field)),
            reverse=key.direction == "desc",
        )
        normalized = present + missing
    return TransformResult(normalized, notices, group_plan, applied, contributors)


def _normalize_row(row: dict[str, Any], fields: list[str], *, strings: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"id": row.get("id")}
    for field_name in fields:
        value = row.get(field_name)
        if strings and value is not None:
            if isinstance(value, bool):
                value = "true" if value else "false"
            elif isinstance(value, dict | list):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                value = str(value)
        result[field_name] = value
    for key, value in row.items():
        if key not in result:
            result[key] = value
    return result


def _group_rows(
    rows: list[dict[str, Any]],
    groupby: str,
) -> tuple[list[dict[str, Any]], GroupPlan, dict[str, list[str]]]:
    if rows and groupby not in rows[0]:
        raise VerboisyError(f"Cannot group by unknown field: {groupby}")

    fields = [
        field_name for field_name in (rows[0] if rows else {}) if field_name not in {"id", groupby}
    ]
    aggregations: dict[str, str] = {}
    removed: list[str] = []

    for field_name in fields:
        observed_values = [row.get(field_name) for row in rows if row.get(field_name) is not None]

        if not observed_values:
            removed.append(field_name)
        elif all(
            isinstance(value, int | float) and not isinstance(value, bool)
            for value in observed_values
        ):
            sum_fields = {"count", "quantity", "employees", "revenue", "funding"}
            aggregations[field_name] = (
                "sum" if field_name in sum_fields or field_name.endswith("_count") else "average"
            )
        else:
            removed.append(field_name)

    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get(groupby), []).append(row)

    result: list[dict[str, Any]] = []

    contributors: dict[str, list[str]] = {}
    for key, members in groups.items():
        digest = hashlib.sha256(
            json.dumps(
                [groupby, key],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]

        output: dict[str, Any] = {
            "id": f"group_{digest}",
            groupby: key,
        }

        for field_name, operation in aggregations.items():
            numeric_values: list[int | float] = []

            for member in members:
                value = member.get(field_name)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    numeric_values.append(value)

            output[field_name] = (
                sum(numeric_values)
                if operation == "sum"
                else (sum(numeric_values) / len(numeric_values) if numeric_values else None)
            )

        contributors[output["id"]] = [str(member["id"]) for member in members]
        result.append(output)

    return result, GroupPlan(groupby, aggregations, tuple(removed)), contributors


def _sort_value(value: Any) -> tuple[int, Any]:
    # Callers partition nulls before sorting so they stay last in both directions.
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int | float):
        return (0, value)
    if isinstance(value, datetime):
        return (0, value.isoformat())
    return (0, str(value).casefold())
