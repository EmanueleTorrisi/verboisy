# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Pagination stops must preserve deferred context reads and click failure order."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from verboisy.core.page_pagination import advance_page


async def test_no_pagination_selector_requires_no_run_context():
    runner = SimpleNamespace(task=SimpleNamespace(pagination_selector=None))
    page = SimpleNamespace(locator=MagicMock())
    # No configuration, ledger or interaction limit is needed without pagination.
    assert not await advance_page(runner, page, "https://example.test/", 0)
    page.locator.assert_not_called()


@pytest.fixture
def pagination():
    control = SimpleNamespace(
        count=AsyncMock(return_value=1),
        is_visible=AsyncMock(return_value=True),
        is_enabled=AsyncMock(return_value=True),
        click=AsyncMock(),
    )
    page = SimpleNamespace(locator=MagicMock(return_value=control))
    runner = SimpleNamespace(
        rid="run",
        task=SimpleNamespace(pagination_selector="#next", max_interactions_per_page=0),
        store=SimpleNamespace(event=MagicMock()),
    )
    return runner, page, control


async def test_interaction_limit_write_failure_prevents_click(pagination):
    runner, page, control = pagination
    runner.store.event.side_effect = OSError("Coverage journal failed")
    # Action configuration is deliberately absent at the interaction limit.
    with pytest.raises(OSError, match="Coverage journal failed"):
        await advance_page(runner, page, "https://example.test/", 0)
    runner.store.event.assert_called_once_with(
        "run", "coverage_gap", {"reason": "interaction_limit", "url": "https://example.test/"}
    )
    control.click.assert_not_awaited()


async def test_pagination_click_failure_propagates(pagination):
    runner, page, control = pagination
    runner.task.max_interactions_per_page = 2
    runner.config = SimpleNamespace(browser_action_timeout_ms=17)
    control.click.side_effect = PlaywrightError("Pagination click failed")
    with pytest.raises(PlaywrightError, match="Pagination click failed"):
        await advance_page(runner, page, "https://example.test/", 0)
    control.click.assert_awaited_once_with(timeout=17)
    runner.store.event.assert_not_called()
