"""
Stealth evasions and browser fingerprint masking.
"""

import random
from typing import List, Dict, Any
from playwright.async_api import Page

from verboisy.utils.logger import get_logger


logger = get_logger(__name__)


class StealthManager:
    """Manages user-agent rotation and anti-detection scripts for Playwright."""

    USER_AGENTS: List[str] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ]

    @classmethod
    def get_random_user_agent(cls) -> str:
        """Return a random modern user agent string."""
        return random.choice(cls.USER_AGENTS)

    @staticmethod
    async def apply_stealth(page: Page) -> None:
        """
        Apply common anti-bot evasion scripts and user agent overrides to a page.

        Args:
            page: The Playwright page instance.
        """
        logger.debug("Applying stealth evasions to page")

        # Override navigator.webdriver
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        )

        # Override plugins and languages to simulate a real user
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            """
        )
