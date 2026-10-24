# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The rendered pipeline applies declared column scopes after navigation checks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.page_capture import CAPTURE_PAGE, capture_rendered_page
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url, snapshot
from verboisy.utils.exceptions import NavigationError


@pytest.mark.parametrize("invalid", [False, True])
async def test_rendered_capture_passes_saved_column_contract(invalid):
    html = "<table><tr><td></td><td>ONE</td></tr><tr><td>Size</td><td>10</td></tr></table>"
    if invalid:
        html = "<p>The requested table disappeared</p>"
    runner = SimpleNamespace(
        task=TaskSpec(column_tables=[{"table": 1}], settle_ms=0),
        config=SimpleNamespace(max_page_bytes=10000, max_snapshot_chars=10000),
        in_scope=lambda _url: True,
        browser=SimpleNamespace(),
    )
    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "oversized": False,
                "url": "https://example.test/",
                "html": html,
                "visible_html": html,
            }
        )
    )
    builder = MagicMock(wraps=snapshot)
    if invalid:
        with pytest.raises(NavigationError, match="Declared column table rejected"):
            await capture_rendered_page(runner, page, canonical_url, builder, CAPTURE_PAGE)
    else:
        captured, url, original, visible = await capture_rendered_page(
            runner, page, canonical_url, builder, CAPTURE_PAGE
        )
        assert url == "https://example.test/" and original == visible == html
        assert {source.scope for source in captured.sources} == {"table1.column2"}
    builder.assert_called_once_with(
        html, "https://example.test/", 10000, column_tables=runner.task.column_tables
    )
