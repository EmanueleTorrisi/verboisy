# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic provenance checks; these do not establish external factual truth."""

import json
import os
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from verboisy.evidence.models import Candidate, FieldRule, Snapshot, TaskSpec, UnitProjectionField
from verboisy.evidence.quote_batch import MAX_QUOTE_BATCH, quotes_observed
from verboisy.evidence.quote_match import quote_observed
from verboisy.evidence.snapshot import canonical_url, whitespace
from verboisy.extractor.dataset import DatasetParseError, parse_dataset
from verboisy.extractor.descriptor_projection import grounded_projected_descriptors
from verboisy.extractor.projection import ProjectionError, project_row
from verboisy.extractor.schema_cache import validate_record
from verboisy.extractor.temporal_projection import grounded_projected_years
from verboisy.extractor.unit_projection import grounded_projected_units


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
    candidate: Candidate,
    page: Snapshot,
    schema: dict[str, Any],
    task: TaskSpec,
    *,
    batch_quotes: bool = True,
) -> list[str]:
    if "id" in candidate.record:
        return ["reserved_output_id"]
    try:
        validate_record(candidate.record, schema)
        json.dumps(candidate.record, allow_nan=False)
    except (ValueError, TypeError):
        return ["schema_invalid"]
    # A projection plan alone is not evidence. Replay it against the captured raw
    # row before trusting the proposed values or their source bindings.
    projection_bindings: dict[str, tuple[str, str]] = {}
    if page.dataset_projection is not None:
        if (
            page.dataset_asset_id is None
            or page.dataset_row_index is None
            or page.dataset_source_row_json is None
        ):
            return ["dataset_projection_not_grounded"]
        try:
            parsed = parse_dataset(
                ("[" + page.dataset_source_row_json + "]").encode("utf-8"), "json"
            )
            raw_row = parsed.rows[0]
            projected = project_row(raw_row, page.dataset_projection)
            if json.dumps(candidate.record, sort_keys=True) != json.dumps(
                projected.values, sort_keys=True
            ):
                return ["dataset_projection_mismatch"]
            unit_fields = [
                field
                for field in page.dataset_projection.fields
                if isinstance(field, UnitProjectionField)
            ]
            if unit_fields and len(grounded_projected_units(candidate, page)) != len(unit_fields):
                return ["dataset_unit_projection_not_grounded"]
            descriptor_count = sum(
                len(getattr(field, "descriptors", ())) for field in page.dataset_projection.fields
            )
            if (
                descriptor_count
                and sum(
                    len(bindings)
                    for bindings in grounded_projected_descriptors(candidate, page).values()
                )
                != descriptor_count
            ):
                return ["dataset_descriptor_projection_not_grounded"]
            year_count = sum(
                getattr(field, "reference_year_source", None) is not None
                for field in page.dataset_projection.fields
            )
            years = grounded_projected_years(candidate, page)
            if len(years) != year_count or set(candidate.temporal_evidence) != set(years):
                return ["dataset_temporal_projection_not_grounded"]
            raw_fields = leaves(raw_row.values)
            for derivation in projected.derivations:
                for pointer in leaves(projected.values):
                    target = derivation.output_pointer
                    if pointer == target or pointer.startswith(target + "/"):
                        source_pointer = derivation.source_pointer + pointer[len(target) :]
                        projection_bindings[pointer] = (
                            source_pointer,
                            json.dumps(
                                raw_fields[source_pointer],
                                ensure_ascii=False,
                                allow_nan=False,
                                separators=(",", ":"),
                            ),
                        )
        except (
            ProjectionError,
            DatasetParseError,
            ValueError,
            KeyError,
            IndexError,
            UnicodeEncodeError,
        ):
            return ["dataset_projection_not_grounded"]
    fields = leaves(candidate.record)
    if not fields or all(v is None for v in fields.values()) or candidate.record == {}:
        return ["empty_record"]
    errors: list[str] = []
    if set(candidate.evidence) - set(fields):
        errors.append("unknown_evidence_pointer")
    sources = {s.id: s for s in page.sources}
    # A default rule belongs only to this verification call. Construct it lazily
    # and reuse it for unspecified fields; explicit rules need no default model.
    default_rule: FieldRule | None = None
    backend = os.environ.get("VERBOISY_QUOTE_MATCHER", "python")
    use_batch = backend == "native" and batch_quotes
    pending: list[tuple[str, Any, str, FieldRule, tuple[str, str, bool]]] = []
    for pointer, value in fields.items():
        if value is None and task.allow_nulls:
            continue
        proof = candidate.evidence.get(pointer)
        if proof is None:
            errors.append(f"{pointer}:missing_evidence")
            continue
        rule = task.field_rules.get(pointer)
        if rule is None:
            if default_rule is None:
                default_rule = FieldRule()
            rule = default_rule
        if page.dataset_projection is not None and proof.transform != "dataset_projection":
            errors.append(f"{pointer}:dataset_projection_expected")
            continue
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
        if proof.transform == "dataset_projection":
            expected = projection_bindings.get(pointer)
            if expected is None:
                errors.append(f"{pointer}:dataset_projection_not_grounded")
            elif rule.source != "auto" or rule.mapping or rule.external:
                errors.append(f"{pointer}:dataset_rule_not_supported")
            elif (proof.source, proof.quote) != expected or source.text != expected[1]:
                errors.append(f"{pointer}:unsupported_dataset_projection")
            continue
        if proof.transform == "dataset":
            if page.dataset_asset_id is None or page.dataset_row_index is None:
                errors.append(f"{pointer}:dataset_proof_not_grounded")
            elif rule.source != "auto" or rule.mapping or rule.external:
                errors.append(f"{pointer}:dataset_rule_not_supported")
            elif proof.quote != source.text or source.text != json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ):
                errors.append(f"{pointer}:unsupported_dataset_value")
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
        job = (whitespace(source.text), quote, proof.transform in ("number", "integer"))
        if use_batch:
            pending.append((pointer, value, proof.transform, rule, job))
            continue
        if not quote_observed(*job, backend=backend):
            errors.append(f"{pointer}:quote_not_observed")
            continue
        if not _value_matches(value, proof.transform, quote, rule):
            errors.append(f"{pointer}:unsupported_value")
    # Only eligible entity-scoped textual proofs enter native matching. Each
    # chunk yields a complete decision list; value authorization remains Python.
    for start in range(0, len(pending), MAX_QUOTE_BATCH):
        checks = pending[start : start + MAX_QUOTE_BATCH]
        observed = quotes_observed([job for _, _, _, _, job in checks], backend="native")
        for (pointer, value, transform, rule, job), found in zip(checks, observed, strict=True):
            if not found:
                errors.append(f"{pointer}:quote_not_observed")
            elif not _value_matches(value, transform, job[1], rule):
                errors.append(f"{pointer}:unsupported_value")
    if pending and errors:
        # Deferred quote failures must retain their original field order relative
        # to missing, URL, projection and scope errors. Identity errors come last.
        order = {pointer: index for index, pointer in enumerate(fields)}
        errors.sort(key=lambda error: order.get(error.rsplit(":", 1)[0], -1))
    for pointer in task.identity_fields:
        try:
            value = lookup(candidate.record, pointer)
            if value is None or isinstance(value, dict | list) or value == "":
                raise ValueError("empty_identity")
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append(f"{pointer}:invalid_identity")
    return errors


def _value_matches(value: Any, transform: str, quote: str, rule: FieldRule) -> bool:
    # Most fields have no explicit mapping. Serialize keys only when the
    # mapping can affect the decision, retaining JSON key semantics exactly.
    mapped = rule.mapping.get(json.dumps(value, ensure_ascii=False)) if rule.mapping else None
    if mapped is not None:
        matches = quote == whitespace(mapped)
    elif transform == "text":
        matches = isinstance(value, str) and whitespace(value) == quote
    elif transform in ("number", "integer"):
        numeric_literal = re.fullmatch(
            r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
            quote,
        )
        matches = bool(
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and numeric_literal
            and Decimal(quote.replace(",", "")) == Decimal(str(value))
        )
        if transform == "integer":
            matches = matches and isinstance(value, int) and not isinstance(value, bool)
    else:
        matches = isinstance(value, bool) and quote.lower() == str(value).lower()
    return matches
