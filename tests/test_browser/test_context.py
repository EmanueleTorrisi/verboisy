from unittest.mock import AsyncMock, Mock

import pytest

import verboisy.browser.context as context
from verboisy.browser.context import BrowserManager
from verboisy.utils.exceptions import NavigationError


@pytest.mark.asyncio
async def test_start_initializes_playwright_browser_context_and_page(
    monkeypatch,
) -> None:
    manager = BrowserManager()

    playwright_context_manager = Mock()
    playwright = Mock()
    browser = Mock()
    browser_context = Mock()
    page = Mock()

    playwright_context_manager.start = AsyncMock(return_value=playwright)
    playwright.chromium.launch = AsyncMock(return_value=browser)
    browser.new_context = AsyncMock(return_value=browser_context)
    browser_context.new_page = AsyncMock(return_value=page)

    monkeypatch.setattr(
        context,
        "async_playwright",
        Mock(return_value=playwright_context_manager),
    )

    get_user_agent = Mock(return_value="test-user-agent")
    apply_stealth = AsyncMock()

    monkeypatch.setattr(
        context.StealthManager,
        "get_random_user_agent",
        get_user_agent,
    )
    monkeypatch.setattr(
        context.StealthManager,
        "apply_stealth",
        apply_stealth,
    )

    monkeypatch.setattr(context.settings, "headless_browser", True)
    monkeypatch.setattr(context.settings, "user_agent_rotation", True)

    result = await manager.start()

    assert result is page
    assert manager._playwright is playwright
    assert manager._browser is browser
    assert manager._context is browser_context
    assert manager._page is page

    playwright_context_manager.start.assert_awaited_once()
    playwright.chromium.launch.assert_awaited_once_with(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    browser.new_context.assert_awaited_once_with(
        user_agent="test-user-agent",
        viewport={"width": 1920, "height": 1080},
    )
    browser_context.new_page.assert_awaited_once()
    apply_stealth.assert_awaited_once_with(page)
    get_user_agent.assert_called_once()

    # Second call exercises the already-initialized branches.
    second_result = await manager.start()

    assert second_result is page
    playwright_context_manager.start.assert_awaited_once()
    playwright.chromium.launch.assert_awaited_once()
    browser.new_context.assert_awaited_once()
    browser_context.new_page.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_without_user_agent_rotation(monkeypatch) -> None:
    manager = BrowserManager()

    playwright_context_manager = Mock()
    playwright = Mock()
    browser = Mock()
    browser_context = Mock()
    page = Mock()

    playwright_context_manager.start = AsyncMock(return_value=playwright)
    playwright.chromium.launch = AsyncMock(return_value=browser)
    browser.new_context = AsyncMock(return_value=browser_context)
    browser_context.new_page = AsyncMock(return_value=page)

    monkeypatch.setattr(
        context,
        "async_playwright",
        Mock(return_value=playwright_context_manager),
    )

    monkeypatch.setattr(
        context.StealthManager,
        "get_random_user_agent",
        Mock(),
    )
    monkeypatch.setattr(
        context.StealthManager,
        "apply_stealth",
        AsyncMock(),
    )

    monkeypatch.setattr(context.settings, "headless_browser", False)
    monkeypatch.setattr(context.settings, "user_agent_rotation", False)

    result = await manager.start()

    assert result is page

    context.StealthManager.get_random_user_agent.assert_not_called()
    browser.new_context.assert_awaited_once_with(
        user_agent=None,
        viewport={"width": 1920, "height": 1080},
    )


@pytest.mark.asyncio
async def test_navigate_to_success(monkeypatch) -> None:
    manager = BrowserManager()
    page = Mock()
    page.goto = AsyncMock()

    manager.start = AsyncMock(return_value=page)
    monkeypatch.setattr(context.settings, "browser_timeout_ms", 5000)

    await manager.navigate_to("https://example.com")

    manager.start.assert_awaited_once()
    page.goto.assert_awaited_once_with(
        "https://example.com",
        timeout=5000,
        wait_until="domcontentloaded",
    )


@pytest.mark.asyncio
async def test_navigate_to_raises_navigation_error(monkeypatch) -> None:
    manager = BrowserManager()
    page = Mock()
    page.goto = AsyncMock(side_effect=RuntimeError("connection failed"))

    manager.start = AsyncMock(return_value=page)

    with pytest.raises(NavigationError) as exc_info:
        await manager.navigate_to("https://example.com")

    assert "Failed to navigate to https://example.com" in str(exc_info.value)
    assert "connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_page_starts_browser_when_missing() -> None:
    manager = BrowserManager()
    page = Mock()

    async def fake_start() -> None:
        manager._page = page

    manager.start = AsyncMock(side_effect=fake_start)

    result = await manager.get_page()

    assert result is page
    manager.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_page_returns_existing_page() -> None:
    manager = BrowserManager()
    page = Mock()
    manager._page = page
    manager.start = AsyncMock()

    result = await manager.get_page()

    assert result is page
    manager.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_closes_all_resources() -> None:
    manager = BrowserManager()

    page = Mock()
    page.close = AsyncMock()

    browser_context = Mock()
    browser_context.close = AsyncMock()

    browser = Mock()
    browser.close = AsyncMock()

    playwright = Mock()
    playwright.stop = AsyncMock()

    manager._page = page
    manager._context = browser_context
    manager._browser = browser
    manager._playwright = playwright

    await manager.close()

    page.close.assert_awaited_once()
    browser_context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()

    assert manager._page is None
    assert manager._context is None
    assert manager._browser is None
    assert manager._playwright is None

    # Second close exercises all "resource absent" branches.
    await manager.close()

