# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""
Browser automation and DOM parsing packages using Playwright.
"""

from .context import BrowserManager
from .dom_parser import DOMParser
from .stealth import StealthManager

__all__ = ["BrowserManager", "StealthManager", "DOMParser"]
