import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from verboisy.browser.context import BrowserManager
from verboisy.utils.exceptions import NavigationError


@pytest.fixture
def browser_case(monkeypatch):
    """Create a browser manager with mocked Playwright resources."""

    config = SimpleNamespace(
        headless_browser=True,
        browser_sandbox=True,
        user_agent_rotation=False,
        browser_timeout_ms=30000,
    )

    manager = BrowserManager(config=config)

    page = MagicMock()
    page.close = AsyncMock()

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.route = AsyncMock()
    context.route_web_socket = AsyncMock()
    context.close = AsyncMock()

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    playwright.stop = AsyncMock()

    starter = MagicMock()
    starter.start = AsyncMock(return_value=playwright)

    monkeypatch.setattr(
        "verboisy.browser.context.async_playwright",
        lambda: starter,
    )

    monkeypatch.setattr(
        "verboisy.browser.context.StealthManager.apply_stealth",
        AsyncMock(),
    )

    return manager, page, context, browser, playwright, starter


@pytest.mark.asyncio
async def test_existing_chromium_starts_without_install(
    browser_case,
    monkeypatch,
):
    manager, page, context, browser, playwright, starter = browser_case

    installer = AsyncMock()

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        installer,
    )

    result = await manager.start()

    assert result is page

    playwright.chromium.launch.assert_awaited_once_with(
        headless=True,
        chromium_sandbox=True,
    )

    installer.assert_not_awaited()

    await manager.close()

    page.close.assert_awaited_once()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_chromium_requires_explicit_install(
    browser_case,
    monkeypatch,
):
    manager, page, context, browser, playwright, starter = browser_case

    playwright.chromium.launch = AsyncMock(
        side_effect=PlaywrightError("Executable doesn't exist at /missing/chromium")
    )

    installer = AsyncMock()

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        installer,
    )

    with pytest.raises(
        NavigationError,
        match="Chromium is not installed",
    ) as exc_info:
        await manager.start()

    assert "playwright install" in str(exc_info.value)

    installer.assert_not_awaited()

    playwright.stop.assert_awaited_once()

    assert manager._playwright is None
    assert manager._browser is None


@pytest.mark.asyncio
async def test_unrelated_browser_error_does_not_install(
    browser_case,
    monkeypatch,
):
    manager, page, context, browser, playwright, starter = browser_case

    playwright.chromium.launch = AsyncMock(
        side_effect=PlaywrightError("Chromium sandbox unavailable")
    )

    installer = AsyncMock()

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        installer,
    )

    with pytest.raises(
        NavigationError,
        match="Browser startup failed",
    ):
        await manager.start()

    installer.assert_not_awaited()

    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_context_failure_cleans_up(
    browser_case,
):
    manager, page, context, browser, playwright, starter = browser_case

    browser.new_context = AsyncMock(side_effect=RuntimeError("Cannot create browser context"))

    with pytest.raises(
        NavigationError,
        match="Browser startup failed",
    ):
        await manager.start()

    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()

    assert manager._browser is None
    assert manager._playwright is None


@pytest.mark.asyncio
async def test_browser_cancellation_cleans_up(
    browser_case,
):
    manager, page, context, browser, playwright, starter = browser_case

    playwright.chromium.launch = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await manager.start()

    playwright.stop.assert_awaited_once()

    assert manager._playwright is None


@pytest.mark.asyncio
async def test_browser_can_retry_after_missing_executable(
    browser_case,
):
    manager, page, context, browser, playwright, starter = browser_case

    playwright.chromium.launch = AsyncMock(
        side_effect=[
            PlaywrightError("Executable doesn't exist at /missing/chromium"),
            browser,
        ]
    )

    with pytest.raises(
        NavigationError,
        match="Chromium is not installed",
    ):
        await manager.start()

    result = await manager.start()

    assert result is page

    assert playwright.chromium.launch.await_count == 2
    assert starter.start.await_count == 2

    await manager.close()
