# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Rejected rendered observations must not reach evidence construction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.page_capture import capture_rendered_page
from verboisy.core.research import CAPTURE_PAGE
from verboisy.evidence.snapshot import canonical_url
from verboisy.utils.exceptions import NavigationError


@pytest.mark.parametrize(
    ("observation", "in_scope", "reason"),
    [
        ({"oversized": True}, True, "Page exceeds configured size limit"),
        (
            {"oversized": False, "url": "javascript:alert(1)"},
            True,
            "Redirect left the declared crawl scope",
        ),
        (
            {"oversized": False, "url": "https://outside.test/"},
            False,
            "Redirect left the declared crawl scope",
        ),
        (
            {
                "oversized": False,
                "url": "https://example.test/",
                "html": "éé",
                "visible_html": "éé",
            },
            True,
            "Page exceeds configured size limit",
        ),
    ],
)
async def test_capture_rejects_before_snapshot_context(observation, in_scope, reason):
    runner = SimpleNamespace(
        task=SimpleNamespace(settle_ms=0),
        config=SimpleNamespace(max_page_bytes=3),
        in_scope=MagicMock(return_value=in_scope),
    )
    page = SimpleNamespace(evaluate=AsyncMock(return_value=observation))
    make_snapshot = MagicMock()
    # The snapshot limit is deliberately absent: rejected observations must not read it.
    with pytest.raises(NavigationError, match=reason):
        await capture_rendered_page(runner, page, canonical_url, make_snapshot, CAPTURE_PAGE)
    page.evaluate.assert_awaited_once_with(CAPTURE_PAGE, 3)
    make_snapshot.assert_not_called()
