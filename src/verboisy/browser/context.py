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
        self._policy_failures: dict[str, int] = {}

    async def _validate_navigation(self, url: str) -> None:
        await validate_url(url, self.config)
        if self.navigation_scope is not None and not self.navigation_scope(url):
            raise NavigationError("Destination is outside the declared crawl scope")

    def _policy_failure(self, category: str) -> None:
        self._policy_failures[category] = min(
            self._policy_failures.get(category, 0) + 1, 1_000_000_000
        )

    def drain_policy_failures(self) -> list[dict[str, Any]]:
        """Return/reset fixed category counts without retaining private request URLs."""
        notices = [
            {"reason": category, "count": count}
            for category, count in sorted(self._policy_failures.items())
        ]
        self._policy_failures.clear()
        return notices

    async def _route(self, route: Route) -> None:
        try:
            request = route.request
            frame = request.frame
            if self._page is None or frame.page != self._page:
                self._policy_failure("unsupported_page_target")
                raise NavigationError("Unsupported page target")
            if frame != self._page.main_frame:
                self._policy_failure("unsupported_frame_target")
                raise NavigationError("Unsupported frame target")
            await validate_url(request.url, self.config)
        except (NavigationError, PlaywrightError, AttributeError, ValueError):
            self._policy_failure("request_policy_denied")
            try:
                await route.abort("blockedbyclient")
            except PlaywrightError:
                self._policy_failure("target_closed")
        else:
            try:
                await route.continue_()
            except PlaywrightError:
                self._policy_failure("target_closed")

    async def _request_paused(self, event: dict[str, Any]) -> None:
        """Primary target Fetch mediation checks every hop; always finish a pause."""
        session = self._request_session
        if session is None:
            return
        request_id = event.get("requestId")
        if not isinstance(request_id, str):
            self._policy_failure("invalid_policy_event")
            return
        denied = False
        try:
            url = event["request"]["url"]
            await validate_url(url, self.config)
            if event["resourceType"] == "Document":
                await self._validate_navigation(url)
        except (NavigationError, PlaywrightError, KeyError, TypeError, ValueError):
            denied = True
            self._policy_failure("request_policy_denied")
        try:
            await session.send(
                "Fetch.failRequest" if denied else "Fetch.continueRequest",
                {"requestId": request_id, **({"errorReason": "BlockedByClient"} if denied else {})},
            )
        except PlaywrightError:
            self._policy_failure("target_closed")

    async def _websocket(self, route: WebSocketRoute) -> None:
        # WebSocket routing would otherwise bypass the HTTP request policy.
        self._policy_failure("unsupported_websocket_target")
        try:
            await route.close()
        except PlaywrightError:
            self._policy_failure("target_closed")

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
                await self._context.route("**/*", self._route)
                await self._context.route_web_socket("**/*", self._websocket)
            if self._page is None:
                self._page = await self._context.new_page()
                if self.config.user_agent_rotation:
                    await StealthManager.apply_stealth(self._page)
            if self._request_session is None:
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

        self._policy_failures.clear()
        if cancellation is not None:
            raise cancellation
