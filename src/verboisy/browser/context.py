# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Playwright lifecycle with request restrictions and reliable cleanup."""

import asyncio
from collections.abc import Callable
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

from verboisy.browser.policy import validate_url
from verboisy.browser.provision import ensure_browser
from verboisy.browser.stealth import StealthManager
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import NavigationError
from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class BrowserManager:
    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.navigation_scope: Callable[[str], bool] | None = None
        self._request_session: CDPSession | None = None

    async def _validate_navigation(self, url: str) -> None:
        await validate_url(url, self.config)
        if self.navigation_scope is not None and not self.navigation_scope(url):
            raise NavigationError("Destination is outside the declared crawl scope")

    async def _route(self, route: Route) -> None:
        try:
            await validate_url(route.request.url, self.config)
        except (NavigationError, PlaywrightError):
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    async def _request_paused(self, event: dict[str, Any]) -> None:
        """Chromium pauses each request, including every redirected document hop."""
        session = self._request_session
        if session is None:
            return
        try:
            url = event["request"]["url"]
            await validate_url(url, self.config)
            if event["resourceType"] == "Document":
                await self._validate_navigation(url)
        except NavigationError:
            await session.send(
                "Fetch.failRequest",
                {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
            )
        else:
            await session.send("Fetch.continueRequest", {"requestId": event["requestId"]})

    async def _websocket(self, route: WebSocketRoute) -> None:
        # WebSocket routing would otherwise bypass the HTTP request policy.
        await route.close()

    async def start(self) -> Page:
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None:
                await ensure_browser(
                    self._playwright.chromium.executable_path, self.config.browser_auto_install
                )
                try:
                    self._browser = await self._playwright.chromium.launch(
                        headless=self.config.headless_browser,
                        channel="chromium",
                        chromium_sandbox=self.config.browser_sandbox,
                    )
                except PlaywrightError as exc:
                    if "Executable doesn't exist at" in str(exc):
                        raise NavigationError(
                            "Chromium is not installed. "
                            "Install it during setup with: "
                            "poetry run python -m playwright install "
                            "--with-deps chromium"
                        ) from exc
                    raise
            if self._context is None:
                user_agent = (
                    StealthManager.get_random_user_agent()
                    if self.config.user_agent_rotation
                    else None
                )
                self._context = await self._browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1920, "height": 1080},
                    accept_downloads=False,
                    service_workers="block",
                )
                self._context.set_default_timeout(self.config.browser_timeout_ms)
                self._context.set_default_navigation_timeout(self.config.browser_timeout_ms)
                if self.navigation_scope is None:
                    await self._context.route("**/*", self._route)
                await self._context.route_web_socket("**/*", self._websocket)
            if self._page is None:
                self._page = await self._context.new_page()
                if self.config.user_agent_rotation:
                    await StealthManager.apply_stealth(self._page)
            if self.navigation_scope is not None and self._request_session is None:
                self._request_session = await self._context.new_cdp_session(self._page)
                self._request_session.on("Fetch.requestPaused", self._request_paused)
                await self._request_session.send(
                    "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}
                )
            return self._page
        except NavigationError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise NavigationError(
                f"Browser startup failed ({type(exc).__name__}). "
                "Check Chromium installation, system dependencies "
                "and BROWSER_SANDBOX support."
            ) from exc
        except BaseException:
            await self.close()
            raise

    async def navigate_to(self, url: str) -> None:
        await self._validate_navigation(url)
        page = await self.start()
        try:
            response = await page.goto(
                url, timeout=self.config.browser_timeout_ms, wait_until="domcontentloaded"
            )
            if response is not None and response.status >= 400:
                raise NavigationError(f"Destination returned HTTP {response.status}")
            await self._validate_navigation(page.url)
        except NavigationError:
            raise
        except Exception as exc:
            raise NavigationError(f"Navigation failed ({type(exc).__name__})") from None

    async def get_page(self) -> Page:
        return self._page if self._page is not None else await self.start()

    async def close(self) -> None:
        cancellation: asyncio.CancelledError | None = None
        for attribute, method in (
            ("_request_session", "detach"),
            ("_page", "close"),
            ("_context", "close"),
            ("_browser", "close"),
            ("_playwright", "stop"),
        ):
            resource = getattr(self, attribute)
            setattr(self, attribute, None)
            if resource is not None:
                try:
                    await getattr(resource, method)()
                except asyncio.CancelledError as exc:
                    # Attempt the remaining resources before propagating cancellation.
                    # Preserve its first instance even if later cleanup is cancelled.
                    if cancellation is None:
                        cancellation = exc
                except Exception as exc:
                    if type(exc).__name__ == "TargetClosedError":
                        continue

                    logger.warning(
                        "Browser cleanup failed", resource=attribute, error_type=type(exc).__name__
                    )

        if cancellation is not None:
            raise cancellation
