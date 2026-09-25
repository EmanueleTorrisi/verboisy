"""Playwright lifecycle with request restrictions and reliable cleanup."""

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    WebSocketRoute,
    async_playwright,
)

from verboisy.browser.policy import validate_url
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

    async def _route(self, route: Route) -> None:
        try:
            await validate_url(route.request.url, self.config)
        except NavigationError:
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    async def _websocket(self, route: WebSocketRoute) -> None:
        # WebSocket routing would otherwise bypass the HTTP request policy.
        await route.close()

    async def start(self) -> Page:
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.config.headless_browser,
                    chromium_sandbox=self.config.browser_sandbox,
                )
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
                await StealthManager.apply_stealth(self._page)
            return self._page
        except Exception as exc:
            await self.close()
            raise NavigationError(
                f"Browser startup failed ({type(exc).__name__}). "
                "Install Chromium with python -m playwright install chromium; "
                "check system dependencies and BROWSER_SANDBOX support."
            ) from None
        except BaseException:
            await self.close()
            raise

    async def navigate_to(self, url: str) -> None:
        await validate_url(url, self.config)
        page = await self.start()
        try:
            response = await page.goto(
                url, timeout=self.config.browser_timeout_ms, wait_until="domcontentloaded"
            )
            if response is not None and response.status >= 400:
                raise NavigationError(f"Destination returned HTTP {response.status}")
            await validate_url(page.url, self.config)
        except NavigationError:
            raise
        except Exception as exc:
            raise NavigationError(f"Navigation failed ({type(exc).__name__})") from None

    async def get_page(self) -> Page:
        return self._page if self._page is not None else await self.start()

    async def close(self) -> None:
        for attribute, method in (
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
                except Exception as exc:
                    logger.warning(
                        "Browser cleanup failed", resource=attribute, error_type=type(exc).__name__
                    )
