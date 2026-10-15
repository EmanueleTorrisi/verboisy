# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Browser lifecycle and network-boundary tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.browser.policy import validate_url
from verboisy.utils.exceptions import NavigationError


@pytest.fixture
def runtime(monkeypatch, config):
    monkeypatch.setattr("verboisy.browser.context.ensure_browser", AsyncMock())
    page = SimpleNamespace(
        add_init_script=AsyncMock(),
        close=AsyncMock(),
        goto=AsyncMock(return_value=None),
        url="https://example.com",
    )
    page.main_frame = SimpleNamespace(page=page)
    session = SimpleNamespace(on=Mock(), send=AsyncMock(), detach=AsyncMock())
    context = SimpleNamespace(
        new_cdp_session=AsyncMock(return_value=session),
        new_page=AsyncMock(return_value=page),
        close=AsyncMock(),
        route=AsyncMock(),
        route_web_socket=AsyncMock(),
        set_default_timeout=Mock(),
        set_default_navigation_timeout=Mock(),
    )
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(
            executable_path="/test/chromium", launch=AsyncMock(return_value=browser)
        ),
        stop=AsyncMock(),
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
        headless=True, channel="chromium", chromium_sandbox=True
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


async def test_requests_are_allowed(runtime, config):
    """Allow browser requests to public network destinations."""
    config.allow_private_network = False
    config.allowed_domains = []

    route = SimpleNamespace(
        request=SimpleNamespace(url="https://8.8.8.8"),
        abort=AsyncMock(),
        continue_=AsyncMock(),
    )

    runtime.manager._page = runtime.page
    route.request.frame = runtime.page.main_frame
    await runtime.manager._route(route)

    route.continue_.assert_awaited_once()
    route.abort.assert_not_awaited()


async def test_websocket_connections_are_blocked(runtime):
    """Block WebSocket connections to prevent bypassing HTTP policy."""
    route = SimpleNamespace(
        close=AsyncMock(),
    )

    await runtime.manager._websocket(route)

    route.close.assert_awaited_once()


async def test_start_cancellation_cleans_up(runtime):
    """Clean up browser resources when startup is cancelled."""
    runtime.browser.new_context.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await runtime.manager.start()

    runtime.browser.close.assert_awaited_once()
    runtime.playwright.stop.assert_awaited_once()

    assert runtime.manager._page is None
    assert runtime.manager._context is None
    assert runtime.manager._browser is None
    assert runtime.manager._playwright is None


@pytest.mark.parametrize(
    "message", ["Executable doesn't exist at /private/path", "PRIVATE PROVIDER DETAIL"]
)
async def test_launch_failures_are_safe(runtime, message):
    from playwright.async_api import Error

    runtime.playwright.chromium.launch.side_effect = Error(message)
    with pytest.raises(NavigationError) as exc:
        await runtime.manager.start()
    assert "/private/path" not in str(exc.value) and "PRIVATE PROVIDER DETAIL" not in str(exc.value)
    runtime.playwright.stop.assert_awaited_once()


async def test_optional_user_agent_mode(runtime, config):
    config.user_agent_rotation = True
    await runtime.manager.start()
    assert runtime.browser.new_context.await_args.kwargs["user_agent"]
    runtime.page.add_init_script.assert_awaited()


async def test_provision_failure_cleans_playwright(runtime, monkeypatch):
    monkeypatch.setattr(
        "verboisy.browser.context.ensure_browser",
        AsyncMock(side_effect=NavigationError("setup failed")),
    )
    with pytest.raises(NavigationError, match="setup failed"):
        await runtime.manager.start()
    runtime.playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_ignores_already_closed_context(config):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verboisy.browser.context import BrowserManager

    class TargetClosedError(Exception):
        pass

    manager = BrowserManager(config)

    manager._context = SimpleNamespace(close=AsyncMock(side_effect=TargetClosedError()))
    manager._browser = None
    manager._playwright = None

    await manager.close()

    assert manager._context is None


@pytest.mark.parametrize("target", ["popup", "frame", "unknown", "closed"])
async def test_unsupported_ownership_and_policy_notices(runtime, target):
    from playwright.async_api import Error

    runtime.manager._page = runtime.page
    frame = (
        SimpleNamespace(page=SimpleNamespace())
        if target == "popup"
        else SimpleNamespace(page=runtime.page, secondary=True)
    )
    route = SimpleNamespace(
        request=SimpleNamespace(frame=frame, url="https://8.8.8.8"),
        abort=AsyncMock(),
        continue_=AsyncMock(),
    )
    if target == "unknown":
        route.request = SimpleNamespace(url="https://8.8.8.8")
    if target == "closed":
        route.abort.side_effect = Error("closed")
    await runtime.manager._route(route)
    route.continue_.assert_not_awaited()
    notices = runtime.manager.drain_policy_failures()
    assert notices and all(set(n) == {"reason", "count"} for n in notices)
    assert runtime.manager.drain_policy_failures() == []


async def test_paused_policy_event_is_safe_and_closed_target_is_counted(runtime):
    from playwright.async_api import Error

    await runtime.manager._request_paused({})
    assert not runtime.manager.drain_policy_failures()
    await runtime.manager.start()
    await runtime.manager._request_paused({})
    runtime.manager._request_session.send.side_effect = Error("closed")
    await runtime.manager._request_paused({"requestId": "r", "request": {}})
    notices = runtime.manager.drain_policy_failures()
    assert {n["reason"] for n in notices} == {
        "invalid_policy_event",
        "request_policy_denied",
        "target_closed",
    }


async def test_continue_target_closure_is_counted(runtime):
    from playwright.async_api import Error

    runtime.manager._page = runtime.page
    route = SimpleNamespace(
        request=SimpleNamespace(frame=runtime.page.main_frame, url="https://8.8.8.8"),
        abort=AsyncMock(),
        continue_=AsyncMock(side_effect=Error("closed")),
    )
    await runtime.manager._route(route)
    assert runtime.manager.drain_policy_failures() == [{"reason": "target_closed", "count": 1}]


async def test_websocket_policy_notice_survives_target_close(runtime):
    from playwright.async_api import Error

    route = SimpleNamespace(close=AsyncMock(side_effect=Error("closed")))
    await runtime.manager._websocket(route)
    assert {n["reason"] for n in runtime.manager.drain_policy_failures()} == {
        "unsupported_websocket_target",
        "target_closed",
    }
