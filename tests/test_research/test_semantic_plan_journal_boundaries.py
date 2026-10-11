# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Semantic plan publication must follow durable persistence and deferred reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.fitness import FieldSemantics
from verboisy.core.planner import TemporalIntent
from verboisy.core.research import ResearchRunner
from verboisy.utils.exceptions import LLMResponseError


@pytest.mark.parametrize("state", ["ready", "failed"])
async def test_semantic_plan_guard_requires_no_request_context(monkeypatch, state):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = state == "ready"
    runner.semantic_plan_failed = state == "failed"
    request = AsyncMock()
    monkeypatch.setattr("verboisy.core.research.classify_field_semantics", request)
    # No client, ledger, goal or extractor exists on this guard-only runner.
    if state == "failed":
        with pytest.raises(LLMResponseError, match="semantic planning already failed"):
            await runner.ensure_field_semantics()
    else:
        await runner.ensure_field_semantics()
    request.assert_not_awaited()


async def test_failed_semantic_plan_write_does_not_publish_state(monkeypatch):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.semantic_plan_ready = False
    baseline = {"/value": FieldSemantics(pointer="/value")}
    classified = {"/value": FieldSemantics(pointer="/value", basis="model")}
    runner.field_semantics = baseline
    runner.temporal_intent = TemporalIntent(mode="latest")
    runner.current_year = 2026
    runner.client = object()
    runner.goal = "Find values"
    runner.schema = {"type": "object", "properties": {"value": {"type": "number"}}}
    runner.rid = "run"
    runner.semantic_planning_available = MagicMock(return_value=True)
    runner.store = SimpleNamespace(event=MagicMock(side_effect=OSError("Ledger write failed")))
    runner.extractor = SimpleNamespace(
        field_semantics=baseline, temporal_intent=None, current_year=None
    )
    request = AsyncMock(return_value=classified)
    monkeypatch.setattr("verboisy.core.research.classify_field_semantics", request)

    with pytest.raises(OSError, match="Ledger write failed"):
        await runner.ensure_field_semantics()

    request.assert_awaited_once()
    assert runner.store.event.call_args.args[:2] == ("run", "field_semantics_plan")
    assert not runner.semantic_plan_ready
    assert runner.field_semantics is baseline
    assert runner.extractor.field_semantics is baseline
    assert runner.extractor.temporal_intent is None
    assert runner.extractor.current_year is None
