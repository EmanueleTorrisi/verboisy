"""
Asynchronous Playwright browser management.
"""

from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from verboisy.utils.logger import get_logger
from verboisy.utils.config import settings
from verboisy.utils.exceptions import NavigationError
from verboisy.browser.stealth import StealthManager


logger = get_logger(__name__)


class BrowserManager:
    """Manages the lifecycle of Playwright browsers, contexts, and pages."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> Page:
        """
        Start Playwright and open a secure browser page.

        Returns:
            Page: The active Playwright page instance.
        """
        if not self._playwright:
            logger.debug("Starting Playwright instance")
            self._playwright = await async_playwright().start()

        if not self._browser:
            logger.debug("Launching Chromium browser", headless=settings.headless_browser)
            self._browser = await self._playwright.chromium.launch(
                headless=settings.headless_browser,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )

        if not self._context:
            user_agent = StealthManager.get_random_user_agent() if settings.user_agent_rotation else None
            logger.debug("Creating browser context", user_agent=user_agent)
            self._context = await self._browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1920, "height": 1080}
            )

        if not self._page:
            self._page = await self._context.new_page()
            await StealthManager.apply_stealth(self._page)

        return self._page

    async def navigate_to(self, url: str) -> None:
        """
        Navigate to a specific URL with timeout handling.

        Args:
            url: The destination URL.
        """
        page = await self.start()
        logger.info("Navigating to URL", url=url)
        try:
            await page.goto(url, timeout=settings.browser_timeout_ms, wait_until="domcontentloaded")
        except Exception as e:
            logger.error("Navigation failed", url=url, error=str(e))
            raise NavigationError(f"Failed to navigate to {url}: {e}", {"url": url})

    async def get_page(self) -> Page:
        """Get the active page, starting the browser if necessary."""
        if not self._page:
            await self.start()
        assert self._page is not None
        return self._page

    async def close(self) -> None:
        """Close browser resources cleanly."""
        logger.debug("Closing browser resources")
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
