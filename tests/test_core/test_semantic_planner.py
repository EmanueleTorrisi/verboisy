# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from unittest.mock import AsyncMock

import pytest
from verboisy.core.planner import TemporalIntent
from verboisy.core.semantic_planner import (
    classify_field_semantics,
)
from verboisy.utils.exceptions import LLMResponseError

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
        },
        "population": {
            "type": "integer",
        },
    },
}


@pytest.mark.asyncio
async def test_classifier_builds_field_scoped_semantics():
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "static",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 0.98,
            },
            {
                "pointer": "/population",
                "temporal_class": "mutable",
                "reference_period": "required",
                "temporal_intent": {
                    "mode": "latest",
                    "start_year": None,
                    "end_year": None,
                },
                "definition_sensitive": True,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 0.95,
            },
        ]
    }

    result = await classify_field_semantics(
        client,
        goal="Find the latest population",
        schema=SCHEMA,
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert result["/name"].basis == "model"
    assert result["/name"].temporal_class == "static"
    assert result["/name"].temporal_intent is None

    population = result["/population"]

    assert population.temporal_class == "mutable"
    assert population.reference_period == "required"
    assert population.temporal_intent == TemporalIntent(mode="latest")
    assert population.definition_sensitive
    assert population.comparable_across_rows


@pytest.mark.asyncio
async def test_explicit_semantics_cannot_be_overridden():
    schema = {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "x-verboisy-temporal-class": "static",
                "x-verboisy-reference-period": "none",
                "x-verboisy-unit-sensitive": True,
            }
        },
    }

    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/value",
                "temporal_class": "mutable",
                "reference_period": "required",
                "temporal_intent": None,
                "definition_sensitive": True,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 0.20,
            }
        ]
    }

    result = await classify_field_semantics(
        client,
        goal="Collect value",
        schema=schema,
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    value = result["/value"]

    assert value.basis == "explicit"
    assert value.temporal_class == "static"
    assert value.reference_period == "none"
    assert value.unit_sensitive
    assert value.temporal_intent is None


@pytest.mark.asyncio
async def test_year_and_range_intents_are_normalized():
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "event",
                "reference_period": "required",
                "temporal_intent": {
                    "mode": "range",
                    "start_year": 2020,
                    "end_year": 1990,
                },
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 0.8,
            },
            {
                "pointer": "/population",
                "temporal_class": "event",
                "reference_period": "required",
                "temporal_intent": {
                    "mode": "year",
                    "start_year": 2000,
                    "end_year": None,
                },
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 0.9,
            },
        ]
    }

    result = await classify_field_semantics(
        client,
        goal="Historical values",
        schema=SCHEMA,
        temporal_intent=TemporalIntent(mode="series"),
        current_year=2026,
    )

    assert result["/name"].temporal_intent == (
        TemporalIntent(
            mode="range",
            start_year=1990,
            end_year=2020,
        )
    )
    assert result["/population"].temporal_intent == (
        TemporalIntent(
            mode="year",
            start_year=2000,
            end_year=2000,
        )
    )


@pytest.mark.asyncio
async def test_empty_schema_needs_no_model_call():
    client = AsyncMock()

    result = await classify_field_semantics(
        client,
        goal="Nothing",
        schema={
            "type": "object",
            "properties": {},
        },
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert result == {}
    client.complete_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"fields": "bad"},
        {"fields": []},
        {
            "fields": [
                {
                    "pointer": "/unknown",
                    "temporal_class": "static",
                    "reference_period": "none",
                    "temporal_intent": None,
                    "definition_sensitive": False,
                    "unit_sensitive": False,
                    "comparable_across_rows": False,
                    "confidence": 1.0,
                }
            ]
        },
        {
            "fields": [
                {
                    "pointer": "/name",
                    "temporal_class": "static",
                    "reference_period": "none",
                    "temporal_intent": None,
                    "definition_sensitive": False,
                    "unit_sensitive": False,
                    "comparable_across_rows": False,
                    "confidence": 1.0,
                },
                {
                    "pointer": "/name",
                    "temporal_class": "static",
                    "reference_period": "none",
                    "temporal_intent": None,
                    "definition_sensitive": False,
                    "unit_sensitive": False,
                    "comparable_across_rows": False,
                    "confidence": 1.0,
                },
            ]
        },
    ],
)
async def test_invalid_or_incomplete_output_fails_closed(
    response,
):
    client = AsyncMock()
    client.complete_json.return_value = response

    with pytest.raises(LLMResponseError):
        await classify_field_semantics(
            client,
            goal="Collect data",
            schema=SCHEMA,
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "temporal",
    [
        {
            "mode": "latest",
            "start_year": 2025,
            "end_year": None,
        },
        {
            "mode": "year",
            "start_year": None,
            "end_year": None,
        },
        {
            "mode": "year",
            "start_year": 2020,
            "end_year": 2021,
        },
        {
            "mode": "range",
            "start_year": 2020,
            "end_year": None,
        },
    ],
)
async def test_invalid_temporal_semantics_fail_closed(
    temporal,
):
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "static",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 1.0,
            },
            {
                "pointer": "/population",
                "temporal_class": "mutable",
                "reference_period": "required",
                "temporal_intent": temporal,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 1.0,
            },
        ]
    }

    with pytest.raises(LLMResponseError):
        await classify_field_semantics(
            client,
            goal="Collect data",
            schema=SCHEMA,
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_year", "end_year", "expected_start", "expected_end"),
    [
        (2000, 2020, 2000, 2020),
        (2020, 2000, 2000, 2020),
    ],
)
async def test_series_intent_preserves_or_normalizes_bounds(
    start_year,
    end_year,
    expected_start,
    expected_end,
):
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "time_series",
                "reference_period": "required",
                "temporal_intent": {
                    "mode": "series",
                    "start_year": start_year,
                    "end_year": end_year,
                },
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 1.0,
            },
            {
                "pointer": "/population",
                "temporal_class": "static",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 1.0,
            },
        ]
    }

    result = await classify_field_semantics(
        client,
        goal="Population through the years",
        schema=SCHEMA,
        temporal_intent=TemporalIntent(mode="series"),
        current_year=2026,
    )

    assert result["/name"].temporal_intent == TemporalIntent(
        mode="series",
        start_year=expected_start,
        end_year=expected_end,
    )


@pytest.mark.asyncio
async def test_model_required_period_without_intent_fails_closed():
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "static",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 1.0,
            },
            {
                "pointer": "/population",
                "temporal_class": "mutable",
                "reference_period": "required",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 1.0,
            },
        ]
    }

    with pytest.raises(LLMResponseError):
        await classify_field_semantics(
            client,
            goal="Latest population",
            schema=SCHEMA,
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
        )


@pytest.mark.asyncio
async def test_explicit_required_period_without_intent_fails_closed():
    schema = {
        "type": "object",
        "properties": {
            "population": {
                "type": "integer",
                "x-verboisy-temporal-class": "mutable",
                "x-verboisy-reference-period": "required",
            }
        },
    }

    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/population",
                "temporal_class": "static",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 0.1,
            }
        ]
    }

    with pytest.raises(LLMResponseError):
        await classify_field_semantics(
            client,
            goal="Latest population",
            schema=schema,
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
        )


@pytest.mark.asyncio
async def test_malformed_field_proposal_fails_closed():
    client = AsyncMock()
    client.complete_json.return_value = {
        "fields": [
            {
                "pointer": "/name",
                "temporal_class": "not-a-valid-class",
                "reference_period": "none",
                "temporal_intent": None,
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": False,
                "confidence": 1.0,
            },
            {
                "pointer": "/population",
                "temporal_class": "mutable",
                "reference_period": "required",
                "temporal_intent": {
                    "mode": "latest",
                    "start_year": None,
                    "end_year": None,
                },
                "definition_sensitive": False,
                "unit_sensitive": False,
                "comparable_across_rows": True,
                "confidence": 1.0,
            },
        ]
    }

    with pytest.raises(LLMResponseError):
        await classify_field_semantics(
            client,
            goal="Latest population",
            schema=SCHEMA,
            temporal_intent=TemporalIntent(mode="latest"),
            current_year=2026,
        )


def test_semantic_plan_event_round_trip():
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.semantic_planner import (
        semantic_plan_event,
        semantic_plan_from_event,
    )

    semantics = {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            reference_period="none",
            temporal_intent=None,
            confidence=0.98,
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=0.95,
            basis="model",
        ),
    }

    event = semantic_plan_event(
        semantics,
        research_year=2026,
        temporal_intent=TemporalIntent(mode="latest"),
    )

    year, intent, restored = semantic_plan_from_event(
        event,
        schema=SCHEMA,
    )

    assert year == 2026
    assert intent == TemporalIntent(mode="latest")
    assert restored == semantics


@pytest.mark.parametrize(
    "mutate",
    [
        lambda event: {
            **event,
            "version": 99,
        },
        lambda event: {
            **event,
            "fields": [],
        },
        lambda event: {
            **event,
            "fields": (event["fields"] + [event["fields"][0]]),
        },
    ],
)
def test_invalid_semantic_plan_event_is_rejected(
    mutate,
):
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.semantic_planner import (
        semantic_plan_event,
        semantic_plan_from_event,
    )

    semantics = {
        "/name": FieldSemantics(
            pointer="/name",
            temporal_class="static",
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            basis="model",
        ),
    }

    event = semantic_plan_event(
        semantics,
        research_year=2026,
        temporal_intent=TemporalIntent(mode="latest"),
    )

    with pytest.raises(ValueError):
        semantic_plan_from_event(
            mutate(event),
            schema=SCHEMA,
        )


def test_required_stored_field_needs_intent():
    from verboisy.core.fitness import (
        FieldSemantics,
    )
    from verboisy.core.semantic_planner import (
        semantic_plan_event,
        semantic_plan_from_event,
    )

    semantics = {
        "/name": FieldSemantics(
            pointer="/name",
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            basis="model",
        ),
    }

    event = semantic_plan_event(
        semantics,
        research_year=2026,
        temporal_intent=TemporalIntent(mode="latest"),
    )

    for field in event["fields"]:
        if field["pointer"] == "/population":
            field["temporal_intent"] = None

    with pytest.raises(ValueError):
        semantic_plan_from_event(
            event,
            schema=SCHEMA,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_field",
    [
        {
            "pointer": "/wrong",
            "temporal_class": "static",
            "reference_period": "none",
            "temporal_intent": None,
            "definition_sensitive": False,
            "unit_sensitive": False,
            "comparable_across_rows": False,
            "confidence": 0.9,
        },
        {
            "pointer": "/name",
            "temporal_class": "mutable",
            "reference_period": "required",
            "temporal_intent": None,
            "definition_sensitive": False,
            "unit_sensitive": False,
            "comparable_across_rows": False,
            "confidence": 0.9,
        },
    ],
)
async def test_semantic_planner_escalates_full_contract_failure(
    invalid_field,
):
    from types import SimpleNamespace

    from verboisy.core.planner import (
        TemporalIntent,
    )
    from verboisy.core.semantic_planner import (
        classify_field_semantics,
    )
    from verboisy.llm.client import LLMClient

    valid_field = {
        "pointer": "/name",
        "temporal_class": "static",
        "reference_period": "none",
        "temporal_intent": None,
        "definition_sensitive": False,
        "unit_sensitive": False,
        "comparable_across_rows": False,
        "confidence": 0.9,
    }

    class StubClient(LLMClient):
        def __init__(self):
            self.config = SimpleNamespace(
                semantic_plan_model="cheap-model",
                escalation_model="strong-model",
            )
            self.model = "default-model"
            self.calls = []
            self.responses = [
                {"fields": [invalid_field]},
                {"fields": [valid_field]},
            ]

        async def complete_json(
            self,
            _system_prompt,
            _user_prompt,
            *,
            model=None,
        ):
            self.calls.append(model)

            return self.responses.pop(0)

    client = StubClient()

    schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
            },
        },
        "required": [
            "name",
        ],
    }

    semantics = await classify_field_semantics(
        client,
        goal="Find organizations",
        schema=schema,
        temporal_intent=TemporalIntent(mode="latest"),
        current_year=2026,
    )

    assert client.calls == [
        "cheap-model",
        "strong-model",
    ]

    assert set(semantics) == {
        "/name",
    }
    assert semantics["/name"].basis == "model"
