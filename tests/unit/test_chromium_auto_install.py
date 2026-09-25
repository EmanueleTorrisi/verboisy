import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from verboisy.browser.context import BrowserManager
from verboisy.utils.exceptions import NavigationError


@pytest.fixture
def browser_case(monkeypatch):
    """Create a BrowserManager with mocked Playwright resources."""

    config = SimpleNamespace(
        headless_browser=True,
        browser_sandbox=False,
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

    process = MagicMock()
    process.wait = AsyncMock(return_value=0)

    installer = AsyncMock(return_value=process)

    monkeypatch.setattr(
        "verboisy.browser.context.asyncio.create_subprocess_exec",
        installer,
    )

    return SimpleNamespace(
        manager=manager,
        browser=browser,
        playwright=playwright,
        page=page,
        process=process,
        installer=installer,
        monkeypatch=monkeypatch,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (
            "linux",
            ["install", "--with-deps", "chromium"],
        ),
        (
            "win32",
            ["install", "chromium"],
        ),
    ],
)
async def test_chromium_installs_when_missing(
    browser_case,
    platform,
    expected,
):
    """Missing Chromium triggers automatic installation."""

    case = browser_case

    case.monkeypatch.setattr(
        "verboisy.browser.context.sys",
        SimpleNamespace(
            executable=sys.executable,
            platform=platform,
        ),
    )

    case.playwright.chromium.launch.side_effect = [
        PlaywrightError("Executable doesn't exist at /missing/chromium"),
        case.browser,
    ]

    page = await case.manager.start()

    assert page is case.page

    assert case.playwright.chromium.launch.await_count == 2

    case.installer.assert_awaited_once_with(
        sys.executable,
        "-m",
        "playwright",
        *expected,
    )

    case.process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_chromium_installation_failure(
    browser_case,
):
    """A failed installation raises NavigationError."""

    case = browser_case

    case.playwright.chromium.launch.side_effect = PlaywrightError(
        "Executable doesn't exist at /missing/chromium"
    )

    case.process.wait.return_value = 1

    with pytest.raises(
        NavigationError,
        match="Browser startup failed",
    ):
        await case.manager.start()

    case.installer.assert_awaited_once()

    assert case.manager._browser is None
    assert case.manager._playwright is None


@pytest.mark.asyncio
async def test_unrelated_browser_error_does_not_install(
    browser_case,
):
    """Do not reinstall Chromium for unrelated launch errors."""

    case = browser_case

    case.playwright.chromium.launch.side_effect = PlaywrightError("Browser crashed unexpectedly")

    with pytest.raises(
        NavigationError,
        match="Browser startup failed",
    ):
        await case.manager.start()

    case.installer.assert_not_awaited()


@pytest.mark.asyncio
async def test_chromium_retry_failure(
    browser_case,
):
    """Handle browser launch failure after installation."""

    case = browser_case

    case.playwright.chromium.launch.side_effect = [
        PlaywrightError("Executable doesn't exist at /missing/chromium"),
        PlaywrightError("Chromium failed to launch after installation"),
    ]

    with pytest.raises(
        NavigationError,
        match="Browser startup failed",
    ):
        await case.manager.start()

    case.installer.assert_awaited_once()

    assert case.playwright.chromium.launch.await_count == 2


@pytest.mark.asyncio
async def test_existing_chromium_skips_installation(
    browser_case,
):
    """Existing Chromium launches without installation."""

    case = browser_case

    page = await case.manager.start()

    assert page is case.page

    case.installer.assert_not_awaited()

    case.playwright.chromium.launch.assert_awaited_once_with(
        headless=True,
        chromium_sandbox=False,
    )
