# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Planning-time semantic classification for user-defined dataset fields."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verboisy.core.fitness import (
    FieldSemantics,
    ReferencePeriod,
    SemanticsBasis,
    TemporalClass,
    build_field_semantics,
    scalar_field_schemas,
)
from verboisy.core.planner import TemporalIntent
from verboisy.llm.client import (
    LLMClient,
    complete_validated_for_role,
)
from verboisy.utils.exceptions import LLMResponseError

SEMANTIC_PLANNER = """Classify the research semantics of user-defined dataset fields.

This is planning only. Do not produce facts, values, sources, URLs, or dataset rows.

Return:
{"fields":[{
  "pointer":"/field",
  "temporal_class":"static|slow_changing|mutable|event|time_series|unknown",
  "reference_period":"none|preferred|required",
  "temporal_intent":{
    "mode":"latest|year|range|series",
    "start_year":null,
    "end_year":null
  } or null,
  "definition_sensitive":false,
  "unit_sensitive":false,
  "methodology_sensitive":false,
  "comparable_across_rows":false,
  "confidence":0.0
}]}

Return every supplied pointer exactly once and no other pointers.

Rules:
- Classify field meaning, not current factual values.
- "static" means normally invariant for the entity.
- "slow_changing" means it can change but not continuously.
- "mutable" means currentness materially affects correctness.
- "event" describes a fact tied to a particular event/date.
- "time_series" means multiple observations across time are part of the requested meaning.
- reference_period="required" when a value cannot be interpreted correctly without its
  observation/reference period.
- "preferred" means temporal provenance improves quality but absence alone need not reject it.
- definition_sensitive means legitimate sources may use materially different definitions.
- unit_sensitive means comparison requires compatible units/scales.
- methodology_sensitive means interpretation depends on compatible measurement methods.
- comparable_across_rows means the dataset should use compatible definitions/methodology/vintage.

Temporal intent is FIELD-SCOPED:
- Unless the user requests a historical period for that field, mutable/current fields default
  to mode="latest".
- Apply a stated year/range only to fields the user's wording actually scopes it to.
- Do not force an unrelated field into the same historical period.
- Static fields normally use null temporal_intent.
- A field with reference_period="required" must have a non-null temporal_intent.

Explicit semantics supplied with a field are authoritative. You may determine temporal_intent
for those fields, but do not override their explicit semantic properties.

Confidence is confidence in the semantic classification only, from 0 to 1.
"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _TemporalProposal(_StrictModel):
    mode: Literal[
        "latest",
        "year",
        "range",
        "series",
    ]
    start_year: int | None = None
    end_year: int | None = None


class _FieldProposal(_StrictModel):
    pointer: str
    temporal_class: TemporalClass
    reference_period: ReferencePeriod
    temporal_intent: _TemporalProposal | None = None
    definition_sensitive: bool
    unit_sensitive: bool
    methodology_sensitive: bool = Field(default=False, strict=True)
    comparable_across_rows: bool
    confidence: float = Field(ge=0.0, le=1.0)


class _SemanticPlanResponse(_StrictModel):
    fields: list[_FieldProposal]


class _StoredFieldProposal(_FieldProposal):
    basis: SemanticsBasis


class _StoredSemanticPlan(_StrictModel):
    version: Literal[1]
    research_year: int = Field(ge=1000, le=9999)
    temporal_intent: _TemporalProposal
    fields: list[_StoredFieldProposal]


def _temporal_intent(
    value: _TemporalProposal | None,
) -> TemporalIntent | None:
    if value is None:
        return None

    start = value.start_year
    end = value.end_year

    if value.mode == "latest":
        if start is not None or end is not None:
            raise ValueError("latest cannot carry year bounds")

        return TemporalIntent(mode="latest")

    if value.mode == "year":
        if start is None:
            raise ValueError("year requires start_year")

        if end is not None and end != start:
            raise ValueError("year bounds must match")

        return TemporalIntent(
            mode="year",
            start_year=start,
            end_year=start,
        )

    if value.mode == "range":
        if start is None or end is None:
            raise ValueError("range requires both bounds")

        return TemporalIntent(
            mode="range",
            start_year=min(start, end),
            end_year=max(start, end),
        )

    if start is not None and end is not None and start > end:
        start, end = end, start

    return TemporalIntent(
        mode="series",
        start_year=start,
        end_year=end,
    )


def _merge(
    baseline: FieldSemantics,
    proposal: _FieldProposal,
) -> FieldSemantics:
    temporal = _temporal_intent(proposal.temporal_intent)

    if (
        proposal.reference_period == "required"
        and temporal is None
        and baseline.basis != "explicit"
    ):
        raise ValueError("required temporal field lacks temporal intent")

    if baseline.basis == "explicit":
        if baseline.reference_period == "required" and temporal is None:
            raise ValueError("required explicit field lacks temporal intent")

        return replace(
            baseline,
            temporal_intent=temporal,
        )

    return FieldSemantics(
        pointer=baseline.pointer,
        temporal_class=proposal.temporal_class,
        reference_period=proposal.reference_period,
        temporal_intent=temporal,
        definition_sensitive=proposal.definition_sensitive,
        unit_sensitive=proposal.unit_sensitive,
        methodology_sensitive=proposal.methodology_sensitive,
        comparable_across_rows=(proposal.comparable_across_rows),
        confidence=proposal.confidence,
        basis="model",
    )


def semantic_plan_event(
    semantics: dict[str, FieldSemantics],
    *,
    research_year: int,
    temporal_intent: TemporalIntent,
) -> dict[str, Any]:
    """Serialize one durable semantic plan event."""

    return {
        "version": 1,
        "research_year": research_year,
        "temporal_intent": temporal_intent.as_event(),
        "fields": [semantics[pointer].as_event() for pointer in sorted(semantics)],
    }


def semantic_plan_from_event(
    value: Any,
    *,
    schema: dict[str, Any],
) -> tuple[
    int,
    TemporalIntent,
    dict[str, FieldSemantics],
]:
    """Restore and validate a persisted semantic plan."""

    try:
        plan = _StoredSemanticPlan.model_validate(value)
    except ValidationError as exc:
        raise ValueError("invalid persisted semantic plan") from exc

    expected = set(scalar_field_schemas(schema))
    pointers = [field.pointer for field in plan.fields]

    if len(pointers) != len(set(pointers)) or set(pointers) != expected:
        raise ValueError("persisted semantic plan does not " "match schema fields")

    try:
        global_intent = cast(
            TemporalIntent,
            _temporal_intent(plan.temporal_intent),
        )

        semantics: dict[
            str,
            FieldSemantics,
        ] = {}

        for field in plan.fields:
            temporal = _temporal_intent(field.temporal_intent)

            if field.reference_period == "required" and temporal is None:
                raise ValueError("required field lacks " "temporal intent")

            semantics[field.pointer] = FieldSemantics(
                pointer=field.pointer,
                temporal_class=(field.temporal_class),
                reference_period=(field.reference_period),
                temporal_intent=temporal,
                definition_sensitive=(field.definition_sensitive),
                unit_sensitive=(field.unit_sensitive),
                methodology_sensitive=field.methodology_sensitive,
                comparable_across_rows=(field.comparable_across_rows),
                confidence=field.confidence,
                basis=field.basis,
            )

    except ValueError as exc:
        raise ValueError("invalid persisted semantic plan") from exc

    return (
        plan.research_year,
        global_intent,
        semantics,
    )


def _validate_semantic_response_contract(
    value: dict[str, Any],
    *,
    baseline: dict[str, FieldSemantics],
    field_schemas: dict[str, dict[str, Any]],
) -> dict[str, FieldSemantics]:
    """Validate and materialize the complete semantic-plan contract."""

    try:
        plan = _SemanticPlanResponse.model_validate(value)
    except ValidationError as exc:
        raise LLMResponseError("Semantic planner returned invalid fields") from exc

    pointers = [field.pointer for field in plan.fields]
    expected = set(field_schemas)

    if len(pointers) != len(set(pointers)) or set(pointers) != expected:
        raise LLMResponseError(
            "Semantic planner returned incomplete " "or unexpected field semantics"
        )

    proposals = {field.pointer: field for field in plan.fields}

    result: dict[str, FieldSemantics] = {}

    try:
        for pointer in field_schemas:
            result[pointer] = _merge(
                baseline[pointer],
                proposals[pointer],
            )
    except ValueError as exc:
        raise LLMResponseError("Semantic planner returned invalid " "temporal semantics") from exc

    return result


async def classify_field_semantics(
    client: LLMClient,
    *,
    goal: str,
    schema: dict[str, Any],
    temporal_intent: TemporalIntent,
    current_year: int,
) -> dict[str, FieldSemantics]:
    """Classify field semantics once before source research begins."""

    field_schemas = scalar_field_schemas(schema)
    baseline = build_field_semantics(schema)

    if not field_schemas:
        return baseline

    semantics: dict[str, FieldSemantics] = await complete_validated_for_role(
        client,
        "semantic_plan",
        SEMANTIC_PLANNER,
        json.dumps(
            {
                "goal": goal,
                "current_year": current_year,
                "default_temporal_intent": (temporal_intent.as_event()),
                "fields": [
                    {
                        "pointer": pointer,
                        "schema": field_schema,
                        "explicit_semantics": (
                            baseline[pointer].as_event()
                            if baseline[pointer].basis == "explicit"
                            else None
                        ),
                    }
                    for pointer, field_schema in field_schemas.items()
                ],
            },
            ensure_ascii=False,
        ),
        lambda value: _validate_semantic_response_contract(
            value,
            baseline=baseline,
            field_schemas=field_schemas,
        ),
    )

    return semantics
