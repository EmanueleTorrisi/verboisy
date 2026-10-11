# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Frontier outcome selection retains lazy ledger reads and failure precedence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.run_outcome import exhausted_frontier_outcome


def test_no_target_does_not_read_records_or_consistency():
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.task = SimpleNamespace()
    runner.store = SimpleNamespace(records=MagicMock(side_effect=AssertionError("Unexpected read")))
    runner.dataset_consistency_gaps = MagicMock(side_effect=AssertionError("Unexpected check"))
    summary = {"pages": {}, "coverage_gaps": 0, "identity_conflicts": 0}
    assert exhausted_frontier_outcome(runner, summary) == ("EXHAUSTED", "observed_scope_exhausted")
    runner.store.records.assert_not_called()
    runner.dataset_consistency_gaps.assert_not_called()


@pytest.mark.asyncio
async def test_failed_consistency_journal_checkpoints_execution_failure():
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.adaptive_frontier = False
    runner.task = SimpleNamespace(target_records=1, max_pages=100)
    runner.config = SimpleNamespace(run_timeout_seconds=10)
    runner.client = SimpleNamespace(total_tokens=17, reserved_tokens=123)
    runner.browser = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    runner.target_met = MagicMock(return_value=False)
    runner.dataset_repair_discovery_available = MagicMock(return_value=False)
    runner.source_scores = MagicMock(return_value={})
    runner.dataset_consistency_gaps = MagicMock(return_value=("/population:unknown_unit",))
    runner.dataset_consistency_repairs = MagicMock(return_value=())
    runner.store = SimpleNamespace(
        recover=MagicMock(),
        records=MagicMock(return_value=[{"population": 2}]),
        summary=MagicMock(
            return_value={"pages": {"failed": 1}, "coverage_gaps": 0, "identity_conflicts": 0}
        ),
        next_page=MagicMock(return_value=None),
        event=MagicMock(side_effect=OSError("Diagnostic write failed")),
        finish=MagicMock(),
    )
    assert await runner.run(1) == ("FAILED", "execution_OSError")
    runner.store.event.assert_called_once_with(
        "run",
        "dataset_consistency_gap",
        {"gaps": ["/population:unknown_unit"], "records": 1, "target_records": 1},
    )
    runner.store.finish.assert_called_once_with("run", "FAILED", "execution_OSError", 17, 123)
    assert runner.store.recover.call_count == 2
    runner.browser.close.assert_awaited_once()
