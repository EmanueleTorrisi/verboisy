# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cleanup failures must not strand claimed pages or lose the run checkpoint."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import BudgetExceededError

from tests.test_research.test_contracts import SCHEMA, task


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("cancel_cleanup", [False, True])
async def test_cleanup_failure_still_recovers_claimed_page_and_saves_accounting(
    tmp_path, interrupted, cancel_cleanup
):
    store = ResearchStore(tmp_path / "run.sqlite3")
    try:
        rid = store.create("Find customers", SCHEMA, TaskSpec.model_validate(task()), None)
        store.queue(rid, "https://people.test/", 0, None)
        runner = ResearchRunner.__new__(ResearchRunner)
        runner.store, runner.rid = store, rid
        runner.adaptive_frontier = False
        runner.client = SimpleNamespace(total_tokens=17, reserved_tokens=123)
        failure = asyncio.CancelledError() if cancel_cleanup else RuntimeError("Cleanup failed")

        async def start():
            assert store.next_page(rid) is not None
            if interrupted:
                raise asyncio.CancelledError()
            raise BudgetExceededError("Request budget")

        runner.browser = SimpleNamespace(
            start=AsyncMock(side_effect=start), close=AsyncMock(side_effect=failure)
        )
        with pytest.raises(type(failure)) as caught:
            await runner.run(1)
        assert caught.value is failure
        state = store.load(rid)
        assert state["status"] == "PAUSED"
        assert state["reason"] == ("interrupted" if interrupted else "model_request_budget")
        assert state["tokens"] == 17
        assert state["reserved"] == 123
        assert store.summary(rid)["pages"] == {"queued": 1}
        runner.browser.close.assert_awaited_once()
    finally:
        store.close()
