"""Deterministic provenance checks; these do not establish external factual truth."""

import json
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from verboisy.evidence.models import Candidate, FieldRule, Snapshot, TaskSpec
from verboisy.evidence.snapshot import canonical_url, whitespace
from verboisy.extractor.schema_builder import SchemaBuilder


def leaves(value: Any, pointer: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return {
            p: v
            for k, item in value.items()
            for p, v in leaves(
                item, pointer + "/" + k.replace("~", "~0").replace("/", "~1")
            ).items()
        }
    if isinstance(value, list) and value:
        return {
            p: v for i, item in enumerate(value) for p, v in leaves(item, pointer + f"/{i}").items()
        }
    return {pointer: value}


def lookup(record: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("Identity fields must be JSON pointers starting with /")
    value: Any = record
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def verify(
    candidate: Candidate, page: Snapshot, schema: dict[str, Any], task: TaskSpec
) -> list[str]:
    try:
        SchemaBuilder.build_model("Record", schema).model_validate(candidate.record)
        json.dumps(candidate.record, allow_nan=False)
    except (ValueError, TypeError):
        return ["schema_invalid"]
    fields = leaves(candidate.record)
    if not fields or all(v is None for v in fields.values()) or candidate.record == {}:
        return ["empty_record"]
    errors: list[str] = []
    if set(candidate.evidence) - set(fields):
        errors.append("unknown_evidence_pointer")
    sources = {s.id: s for s in page.sources}
    for pointer, value in fields.items():
        if value is None and task.allow_nulls:
            continue
        proof = candidate.evidence.get(pointer)
        if proof is None:
            errors.append(f"{pointer}:missing_evidence")
            continue
        rule = task.field_rules.get(pointer, FieldRule())
        if proof.transform == "page_url":
            if rule.source != "page_url" or value != page.url or proof.source != "page":
                errors.append(f"{pointer}:page_url_not_authorized")
            continue
        source = sources.get(proof.source)
        if source is None or source.scope != candidate.scope:
            errors.append(f"{pointer}:source_outside_entity")
            continue
        if rule.source == "page_url":
            errors.append(f"{pointer}:expected_page_url")
            continue
        looks_url = isinstance(value, str) and value.lower().startswith(("https://", "http://"))
        if proof.transform == "href" or looks_url or rule.source == "link":
            if (
                proof.transform != "href"
                or source.kind != "link"
                or canonical_url(str(value)) != source.href
            ):
                errors.append(f"{pointer}:url_not_observed")
            elif rule.external and urlsplit(str(value)).hostname == urlsplit(page.url).hostname:
                errors.append(f"{pointer}:external_url_required")
            continue
        quote = whitespace(proof.quote)
        boundary = (
            r"(?<![\w.,+\u2212-])" + re.escape(quote) + r"(?!\w|[.,]\d)"
            if proof.transform in ("number", "integer")
            else r"(?<!\w)" + re.escape(quote) + r"(?!\w)"
        )
        if not quote or not re.search(boundary, whitespace(source.text)):
            errors.append(f"{pointer}:quote_not_observed")
            continue
        mapped = rule.mapping.get(json.dumps(value, ensure_ascii=False))
        if mapped is not None:
            matches = quote == whitespace(mapped)
        elif proof.transform == "text":
            matches = isinstance(value, str) and whitespace(value) == quote
        elif proof.transform in ("number", "integer"):
            matches = bool(
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", quote)
                and Decimal(quote) == Decimal(str(value))
            )
            if proof.transform == "integer":
                matches = matches and isinstance(value, int) and not isinstance(value, bool)
        else:
            matches = isinstance(value, bool) and quote.lower() == str(value).lower()
        if not matches:
            errors.append(f"{pointer}:unsupported_value")
    for pointer in task.identity_fields:
        try:
            value = lookup(candidate.record, pointer)
            if value is None or isinstance(value, dict | list) or value == "":
                raise ValueError("empty_identity")
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"{pointer}:invalid_identity")
    return errors
