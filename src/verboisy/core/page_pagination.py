# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Advance a rendered page only through the existing bounded pagination controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import Page

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


async def advance_page(
    runner: ResearchRunner,
    page: Page,
    url: str,
    interaction: int,
) -> bool:
    """Return true only after a permitted pagination click succeeds."""
    selector = runner.task.pagination_selector
    if not selector:
        return False
    control = page.locator(selector)
    if (
        await control.count() != 1
        or not await control.is_visible()
        or not await control.is_enabled()
    ):
        return False
    if interaction == runner.task.max_interactions_per_page:
        runner.store.event(runner.rid, "coverage_gap", {"reason": "interaction_limit", "url": url})
        return False
    # The caller increments its interaction count only after this await succeeds.
    await control.click(timeout=runner.config.browser_action_timeout_ms)
    return True
