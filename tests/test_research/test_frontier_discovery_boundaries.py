# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Frontier recovery must preserve deferred reads and failed-write ordering."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import Snapshot, Source


@pytest.fixture
def frontier():
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    runner.task = SimpleNamespace(max_links_per_page=3)
    runner.adaptive_frontier = True
    runner.frontier_batch_size = MagicMock(return_value=1)
    runner.in_scope = lambda url: url.startswith("https://example.test/")
    runner.store = SimpleNamespace(queue=MagicMock(), defer=MagicMock(), event=MagicMock())
    page = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T00:00:00Z",
        content_hash="hash",
        sources=[
            Source(id="a", kind="link", scope="page", text="A", href="https://example.test/a"),
            Source(id="b", kind="link", scope="page", text="B", href="https://example.test/b"),
            Source(
                id="outside",
                kind="link",
                scope="page",
                text="Outside",
                href="https://outside.test/",
            ),
        ],
        truncated=False,
    )
    return runner, page


def test_ordinary_frontier_does_not_resolve_adaptive_budget(frontier):
    runner, page = frontier
    runner.adaptive_frontier = False
    runner.frontier_batch_size.side_effect = AssertionError("Adaptive budget was requested")
    runner.discover(page, 2, ["b"])
    assert [call.args[1] for call in runner.store.queue.call_args_list] == [
        "https://example.test/b",
        "https://example.test/a",
    ]
    runner.frontier_batch_size.assert_not_called()
    runner.store.defer.assert_not_called()
    runner.store.event.assert_not_called()


@pytest.mark.parametrize("failed_write", ["queue", "defer"])
def test_incomplete_frontier_writes_do_not_publish_success(frontier, failed_write):
    runner, page = frontier
    getattr(runner.store, failed_write).side_effect = OSError("Ledger write interrupted")
    with pytest.raises(OSError, match="Ledger write interrupted"):
        runner.discover(page, 2, ["b"])
    runner.store.queue.assert_called_once_with("run", "https://example.test/b", 3, page.url)
    if failed_write == "queue":
        runner.store.defer.assert_not_called()
    else:
        runner.store.defer.assert_called_once_with("run", "https://example.test/a", 3, page.url)
    runner.store.event.assert_not_called()
