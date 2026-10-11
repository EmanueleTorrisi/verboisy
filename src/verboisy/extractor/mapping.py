# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Conservative schema mapping suggestions; sampled compatibility is not acceptance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from verboisy.evidence.models import ProjectionPlan, UnitProjectionField
from verboisy.extractor.dataset import ParsedDataset
from verboisy.extractor.profile import DatasetProfile
from verboisy.extractor.projection import ProjectionError, _parts, project_row
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.utils.exceptions import ExtractionError, VerboisyError


class SchemaMappingError(VerboisyError):
    """A mapping cannot be proposed or validated under the declared policy."""


@dataclass(frozen=True)
class MappingDecision:
    target: str
    source: str | None
    basis: str | None
    candidates: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class MappingSuggestion:
    asset_sha256: str
    schema_sha256: str
    decisions: tuple[MappingDecision, ...]
    unmapped_profile_pointers: tuple[str, ...]
    profile_incomplete: bool
    plan_json: str | None
    policy_version: str = "1"

    @property
    def plan(self) -> ProjectionPlan | None:
        return (
            None if self.plan_json is None else ProjectionPlan.model_validate_json(self.plan_json)
        )


COMPLEX = frozenset(
    {
        "$ref",
        "$dynamicRef",
        "allOf",
        "anyOf",
        "oneOf",
        "if",
        "then",
        "else",
        "not",
        "dependentSchemas",
        "patternProperties",
        "unevaluatedProperties",
    }
)


def _schema(schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        normalized = SchemaBuilder.normalize(schema)
    except ExtractionError:
        raise SchemaMappingError("Invalid target schema") from None
    try:
        encoded = json.dumps(
            normalized, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeEncodeError:
        raise SchemaMappingError("Target schema is not finite UTF-8 JSON") from None
    return normalized, hashlib.sha256(encoded).hexdigest()


def _targets(node: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    if len(pointer.split("/")) > 33 or len(pointer.encode("utf-8")) > 8192:
        raise SchemaMappingError("Target schema mapping limits exceeded")
    if (
        isinstance(node, dict)
        and not COMPLEX.intersection(node)
        and node.get("type") == "object"
        and node.get("properties")
    ):
        for key, definition in node["properties"].items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _targets(definition, pointer + "/" + escaped)
    else:
        yield pointer, node


def suggest_mapping(
    profile: DatasetProfile,
    schema: dict[str, Any],
    *,
    aliases: dict[str, Sequence[str]] | None = None,
) -> MappingSuggestion:
    """Prefer exact pointers, then unique caller-supplied aliases; never guess coercions.

    Suggestions are bound to the profile's original asset hash and normalized
    schema hash. A complete suggestion is still only a proposal: validate_mapping
    replays every actual row before returning an explicit plan for ingestion.
    """
    if profile.profile_version != "1":
        raise SchemaMappingError("Unsupported profile version")
    normalized, schema_hash = _schema(schema)
    root = normalized["items"] if normalized["type"] == "array" else normalized
    targets = list(_targets(root))
    if len(targets) > 100:
        raise SchemaMappingError("Target schema mapping limits exceeded")
    allowed = {pointer for pointer, _ in targets}
    aliases = aliases or {}
    for target, sources in aliases.items():
        if (
            target not in allowed
            or not isinstance(sources, Sequence)
            or isinstance(sources, str | bytes)
            or not 1 <= len(sources) <= 100
        ):
            raise SchemaMappingError("Invalid alias declarations")
        for source in sources:
            if not isinstance(source, str) or len(source) > 8192:
                raise SchemaMappingError("Invalid alias declarations")
            try:
                _parts(source)
            except ProjectionError:
                raise SchemaMappingError("Invalid alias pointer") from None
    fields = {field.pointer: field for field in profile.fields}
    decisions, proposed, used = [], [], []
    for target, definition in targets:
        if (
            not target
            or not isinstance(definition, dict)
            or COMPLEX.intersection(definition)
            or "type" not in definition
        ):
            decisions.append(MappingDecision(target, None, None, (), "unsupported_schema"))
            continue
        candidates = (
            (target,)
            if target in fields
            else tuple(
                dict.fromkeys(source for source in aliases.get(target, ()) if source in fields)
            )
        )
        basis = "exact" if target in fields else "caller_alias"
        if len(candidates) != 1:
            decisions.append(
                MappingDecision(
                    target, None, basis, candidates, "ambiguous" if candidates else "unobserved"
                )
            )
            continue
        source = candidates[0]
        field = fields[source]
        types = definition["type"]
        permitted = set(types if isinstance(types, list) else [types])
        if "number" in permitted:
            permitted.add("integer")
        if field.missing_rows:
            status = "missing_values"
        elif not set(field.observed_types) <= permitted:
            status = "incompatible_types"
        else:
            status = "suggested"
            proposed.append({"source": source, "target": target, "conversion": "identity"})
            used.append(source)
        decisions.append(MappingDecision(target, source, basis, candidates, status))
    plan = (
        ProjectionPlan.model_validate({"fields": proposed})
        if len(proposed) == len(targets)
        else None
    )
    unmapped = tuple(
        pointer
        for pointer in fields
        if not any(
            pointer == source
            or pointer.startswith(source + "/")
            or source.startswith(pointer + "/")
            for source in used
        )
    )
    return MappingSuggestion(
        profile.asset_sha256,
        schema_hash,
        tuple(decisions),
        unmapped,
        profile.rows_truncated or profile.fields_truncated or profile.oversized_pointers_skipped,
        plan.model_dump_json() if plan is not None else None,
    )


def declared_mapping(
    profile: DatasetProfile, schema: dict[str, Any], plan: ProjectionPlan
) -> MappingSuggestion:
    """Bind caller-chosen conversions to an asset and schema, pending full-row validation."""
    if profile.profile_version != "1":
        raise SchemaMappingError("Unsupported profile version")
    _, schema_hash = _schema(schema)
    used = [field.source for field in plan.fields]
    used.extend(
        source
        for field in plan.fields
        if (source := getattr(field, "reference_year_source", None)) is not None
    )
    used.extend(
        field.unit_source for field in plan.fields if isinstance(field, UnitProjectionField)
    )
    used.extend(
        binding.source for field in plan.fields for binding in getattr(field, "descriptors", ())
    )
    unmapped = tuple(
        field.pointer
        for field in profile.fields
        if not any(
            field.pointer == source
            or field.pointer.startswith(source + "/")
            or source.startswith(field.pointer + "/")
            for source in used
        )
    )
    return MappingSuggestion(
        profile.asset_sha256,
        schema_hash,
        tuple(
            MappingDecision(
                field.target, field.source, "declared_plan", (field.source,), "declared"
            )
            for field in plan.fields
        ),
        unmapped,
        profile.rows_truncated or profile.fields_truncated or profile.oversized_pointers_skipped,
        plan.model_dump_json(),
    )


def validate_mapping(
    dataset: ParsedDataset,
    schema: dict[str, Any],
    suggestion: MappingSuggestion,
) -> ProjectionPlan:
    """Replay all captured rows against the authoritative schema; never sample acceptance."""
    _, schema_hash = _schema(schema)
    if (
        suggestion.policy_version != "1"
        or dataset.sha256 != suggestion.asset_sha256
        or schema_hash != suggestion.schema_sha256
    ):
        raise SchemaMappingError("Mapping policy, asset or schema binding differs")
    plan = suggestion.plan
    if plan is None or not dataset.rows:
        raise SchemaMappingError("Mapping is unresolved or dataset is empty")
    model = SchemaBuilder.build_model("MappedRecord", schema)
    try:
        for row in dataset.rows:
            model.model_validate(project_row(row, plan).values)
    except (ProjectionError, ValueError):
        raise SchemaMappingError("Mapping fails full-row projection or schema validation") from None
    return plan
