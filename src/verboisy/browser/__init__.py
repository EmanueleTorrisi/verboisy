"""
Browser automation and DOM parsing packages using Playwright.
"""

from .context import BrowserManager
from .stealth import StealthManager
from .dom_parser import DOMParser

__all__ = ["BrowserManager", "StealthManager", "DOMParser"]
