# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Scoped Chromium requests are checked individually across every redirect hop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError

from tests.test_browser.test_context import runtime as browser_runtime


@pytest.fixture
def runtime(monkeypatch, config):
    return browser_runtime.__wrapped__(monkeypatch, config)


def manager():
    browser = BrowserManager(Settings(_env_file=None, allow_private_network=True))
    browser.navigation_scope = lambda url: url.startswith("http://localhost/safe/")
    browser._request_session = SimpleNamespace(send=AsyncMock(), detach=AsyncMock(), on=Mock())
    return browser


def paused(url, resource_type="Document", request_id="request"):
    return {"requestId": request_id, "request": {"url": url}, "resourceType": resource_type}


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/excluded", "http://localhost/outside", "file:///private/path"]
)
async def test_excluded_document_fails_before_request(url):
    browser = manager()
    await browser._request_paused(paused(url))
    browser._request_session.send.assert_awaited_once_with(
        "Fetch.failRequest", {"requestId": "request", "errorReason": "BlockedByClient"}
    )


async def test_every_redirect_hop_checked():
    browser = manager()
    for index, url in enumerate(
        ["http://localhost/safe/start", "http://localhost/safe/hop", "http://127.0.0.1/excluded"]
    ):
        await browser._request_paused(paused(url, request_id=str(index)))
    assert browser._request_session.send.await_args_list == [
        (("Fetch.continueRequest", {"requestId": "0"}), {}),
        (("Fetch.continueRequest", {"requestId": "1"}), {}),
        (("Fetch.failRequest", {"requestId": "2", "errorReason": "BlockedByClient"}), {}),
    ]


@pytest.mark.parametrize("resource_type", ["Document", "Image"])
async def test_public_resources_continue(resource_type):
    browser = manager()
    url = (
        "http://localhost/safe/end" if resource_type == "Document" else "http://localhost/asset.png"
    )
    await browser._request_paused(paused(url, resource_type))
    browser._request_session.send.assert_awaited_once_with(
        "Fetch.continueRequest", {"requestId": "request"}
    )


async def test_private_resources_still_rejected():
    browser = manager()
    browser.config.allow_private_network = False
    await browser._request_paused(paused("http://127.0.0.1/asset.png", "Image"))
    assert browser._request_session.send.await_args.args[0] == "Fetch.failRequest"


async def test_late_event_after_session_cleanup_is_harmless():
    browser = manager()
    browser._request_session = None
    await browser._request_paused(paused("http://localhost/safe/start"))


async def test_scoped_start_attaches_once_and_cleanup_detaches(runtime):
    session = SimpleNamespace(send=AsyncMock(), detach=AsyncMock(), on=Mock())
    runtime.manager.navigation_scope = lambda _: True
    runtime.context.new_cdp_session = AsyncMock(return_value=session)
    assert await runtime.manager.start() is runtime.page
    assert await runtime.manager.start() is runtime.page
    runtime.context.route.assert_not_awaited()
    runtime.context.new_cdp_session.assert_awaited_once_with(runtime.page)
    session.on.assert_called_once_with("Fetch.requestPaused", runtime.manager._request_paused)
    session.send.assert_awaited_once_with(
        "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
    )
    await runtime.manager.close()
    session.detach.assert_awaited_once()
    assert runtime.manager._request_session is None


async def test_guard_enable_failure_cleans_up(runtime):
    session = SimpleNamespace(
        send=AsyncMock(side_effect=RuntimeError("enable failed")), detach=AsyncMock(), on=Mock()
    )
    runtime.manager.navigation_scope = lambda _: True
    runtime.context.new_cdp_session = AsyncMock(return_value=session)
    with pytest.raises(NavigationError, match="startup failed"):
        await runtime.manager.start()
    session.detach.assert_awaited_once()
    runtime.context.close.assert_awaited_once()


async def test_direct_navigation_rejected_before_browser_start():
    browser = manager()
    browser.start = AsyncMock()
    with pytest.raises(NavigationError, match="crawl scope"):
        await browser.navigate_to("http://localhost/outside")
    browser.start.assert_not_awaited()
