# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real Chromium capture of a frozen column table; no model or public HTTP calls."""

import os
from pathlib import Path

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.core.page_capture import CAPTURE_PAGE
from verboisy.evidence.models import ColumnTableSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.utils.config import Settings

pytestmark = pytest.mark.browser


async def test_rendered_nasa_table_retains_column_coordinates():
    fixture = Path(__file__).parents[1] / "fixtures/pages/nasa_planetary_factsheet.html"
    manager = BrowserManager(
        Settings(
            _env_file=None,
            browser_auto_install=False,
            browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
        )
    )
    try:
        page = await manager.start()
        # The fixture contains external links and assets; this test fetches none of them.
        await page.route("**/*", lambda route: route.abort())
        await page.set_content(fixture.read_text(encoding="utf-8"), wait_until="domcontentloaded")
        rendered = await page.evaluate(CAPTURE_PAGE, 100000)
        assert not rendered["oversized"]
        captured = snapshot(
            rendered["visible_html"],
            "https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
            column_tables=[ColumnTableSpec(table=1)],
        )
        assert not captured.truncated
        sources = {source.id: source for source in captured.sources}
        expected = [
            ("MERCURY", "4879", "3.7", "0"),
            ("VENUS", "12,104", "8.9", "0"),
            ("EARTH", "12,756", "9.8", "1"),
        ]
        for column, values in enumerate(expected, 2):
            for row, value in zip((1, 3, 5, 19), values, strict=True):
                source = sources[f"table1.row{row}.column{column}.value"]
                assert source.text == value
                assert source.scope == f"table1.column{column}"
    finally:
        await manager.close()
