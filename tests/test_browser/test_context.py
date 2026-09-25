"""Browser lifecycle and network-boundary tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.browser.policy import validate_url
from verboisy.utils.exceptions import NavigationError


@pytest.fixture
def runtime(monkeypatch, config):
    page = SimpleNamespace(
        add_init_script=AsyncMock(),
        close=AsyncMock(),
        goto=AsyncMock(return_value=None),
        url="https://example.com",
    )
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page),
        close=AsyncMock(),
        route=AsyncMock(),
        route_web_socket=AsyncMock(),
        set_default_timeout=Mock(),
        set_default_navigation_timeout=Mock(),
    )
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)), stop=AsyncMock()
    )
    monkeypatch.setattr(
        "verboisy.browser.context.async_playwright",
        Mock(return_value=SimpleNamespace(start=AsyncMock(return_value=playwright))),
    )
    return SimpleNamespace(
        page=page,
        context=context,
        browser=browser,
        playwright=playwright,
        manager=BrowserManager(config),
    )


async def test_start_idempotent_and_sandboxed(runtime, config):
    config.browser_sandbox = True
    page = await runtime.manager.start()
    assert await runtime.manager.start() is page
    runtime.playwright.chromium.launch.assert_awaited_once_with(
        headless=True, chromium_sandbox=True
    )
    assert runtime.browser.new_context.await_args.kwargs["accept_downloads"] is False
    assert runtime.browser.new_context.await_args.kwargs["service_workers"] == "block"
    runtime.context.route.assert_awaited_once()
    runtime.context.route_web_socket.assert_awaited_once()
    await runtime.manager.close()


async def test_close_continues_after_failure(runtime):
    await runtime.manager.start()
    runtime.page.close.side_effect = RuntimeError("close failed")
    await runtime.manager.close()
    runtime.playwright.stop.assert_awaited_once()
    runtime.browser.close.assert_awaited_once()
    assert runtime.manager._page is None
    await runtime.manager.close()


async def test_start_failure_cleans_up(runtime):
    runtime.browser.new_context.side_effect = RuntimeError("start failed")
    with pytest.raises(NavigationError, match="startup failed"):
        await runtime.manager.start()
    runtime.browser.close.assert_awaited_once()
    runtime.playwright.stop.assert_awaited_once()


async def test_navigate(runtime):
    await runtime.manager.navigate_to("https://example.com")
    runtime.page.goto.assert_awaited_once_with(
        "https://example.com", timeout=30000, wait_until="domcontentloaded"
    )


async def test_http_error(runtime):
    runtime.page.goto.return_value = SimpleNamespace(status=403)
    with pytest.raises(NavigationError, match="403"):
        await runtime.manager.navigate_to("https://example.com")


async def test_navigate_wraps_error(runtime):
    runtime.page.goto.side_effect = RuntimeError("secret")
    with pytest.raises(NavigationError) as exc:
        await runtime.manager.navigate_to("https://example.com")
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,x",
        "https://user:pass@example.com",
        "http://[::1]:bad",
    ],
)
async def test_non_http_and_credentials_blocked(config, url):
    with pytest.raises(NavigationError):
        await validate_url(url, config)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://[::1]",
        "http://10.0.0.1",
        "http://169.254.169.254",
        "http://0.0.0.0",
    ],
)
async def test_private_network_blocked(config, url):
    config.allow_private_network = False
    with pytest.raises(NavigationError):
        await validate_url(url, config)


async def test_dns_private_address_blocked(config, monkeypatch):
    config.allow_private_network = False
    import asyncio

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop, "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("127.0.0.1", 80))])
    )
    with pytest.raises(NavigationError):
        await validate_url("http://internal.example", config)


async def test_public_literal_allowed(config):
    config.allow_private_network = False
    await validate_url("https://8.8.8.8", config)


async def test_allowlist_exact_host(config):
    config.allowed_domains = ["example.com"]
    await validate_url("https://example.com", config)
    with pytest.raises(NavigationError):
        await validate_url("https://example.com.attacker.test", config)


async def test_requests_are_intercepted(runtime, config):
    config.allow_private_network = False
    route = SimpleNamespace(
        request=SimpleNamespace(url="http://127.0.0.1"), abort=AsyncMock(), continue_=AsyncMock()
    )
    await runtime.manager._route(route)
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()


async def test_get_page(runtime):
    assert await runtime.manager.get_page() is runtime.page
    assert await runtime.manager.get_page() is runtime.page
