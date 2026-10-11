# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Evidence preparation must preserve journal and provider failure boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.page_batches import prepare_page_batches
from verboisy.core.research import ResearchRunner
from verboisy.utils.exceptions import BudgetExceededError, LLMResponseError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["oversized", "semantic"])
async def test_gap_write_failure_precedes_semantic_failure_publication(failure):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.config = SimpleNamespace(max_dom_chars=100)
    runner.adaptive_frontier = False
    runner.store = SimpleNamespace(event=MagicMock(side_effect=OSError("Gap journal failed")))
    runner.ensure_field_semantics = AsyncMock(side_effect=LLMResponseError("Invalid plan"))
    split_sources = MagicMock(return_value=[[object()]])
    if failure == "oversized":
        split_sources.side_effect = ValueError("Block too large")

    with pytest.raises(OSError, match="Gap journal failed"):
        await prepare_page_batches(runner, object(), split_sources)

    assert not hasattr(runner, "semantic_plan_failed")
    reason = "oversized_evidence_block" if failure == "oversized" else "invalid_semantic_plan"
    runner.store.event.assert_called_once_with("run", "coverage_gap", {"reason": reason})
    if failure == "oversized":
        runner.ensure_field_semantics.assert_not_awaited()
    else:
        runner.ensure_field_semantics.assert_awaited_once()


@pytest.mark.asyncio
async def test_semantic_request_budget_propagates_without_invalid_plan_journal():
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.config = SimpleNamespace(max_dom_chars=100)
    runner.adaptive_frontier = False
    runner.store = SimpleNamespace(event=MagicMock())
    runner.ensure_field_semantics = AsyncMock(side_effect=BudgetExceededError("Budget exhausted"))

    with pytest.raises(BudgetExceededError, match="Budget exhausted"):
        await prepare_page_batches(runner, object(), MagicMock(return_value=[[object()]]))

    runner.store.event.assert_not_called()
    assert not hasattr(runner, "semantic_plan_failed")
