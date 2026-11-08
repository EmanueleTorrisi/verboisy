# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""The real runner persists timeout and cleanup when browser startup exceeds its ceiling."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings


async def test_startup_inside_runner_deadline(tmp_path):
    store = ResearchStore(tmp_path / "run.db")
    try:
        rid = store.create("Synthetic", {"type": "object"}, TaskSpec(), None)
        runner = ResearchRunner(store, rid, Settings(_env_file=None, run_timeout_seconds=0.01))

        startup_entered = asyncio.Event()
        startup_cancelled = asyncio.Event()

        async def start():
            startup_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                startup_cancelled.set()
                raise

        close = AsyncMock()
        runner.browser = SimpleNamespace(start=start, close=close)
        # This is a hang guard, not an execution-speed requirement.
        status, reason = await asyncio.wait_for(runner.run(1), timeout=5.0)
        assert status == "PAUSED" and reason == "run_timeout"
        assert startup_entered.is_set()
        assert startup_cancelled.is_set()
        assert store.load(rid)["reason"] == "run_timeout"
        close.assert_awaited_once()
    finally:
        store.close()


async def test_capture_policy_gap_is_safe_and_bound_to_snapshot():
    from unittest.mock import Mock

    from verboisy.core.page_capture import capture_rendered_page
    from verboisy.evidence.snapshot import canonical_url, snapshot

    runner = SimpleNamespace(
        task=SimpleNamespace(settle_ms=0),
        config=SimpleNamespace(max_page_bytes=10000, max_snapshot_chars=1000),
        in_scope=lambda _url: True,
        browser=SimpleNamespace(
            drain_policy_failures=lambda: [{"reason": "unsupported_page_target", "count": 2}]
        ),
        store=SimpleNamespace(event=Mock()),
        rid="run",
    )
    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "oversized": False,
                "url": "https://example.test/",
                "html": "<p>A</p>",
                "visible_html": "<p>A</p>",
            }
        )
    )
    captured, *_ = await capture_rendered_page(runner, page, canonical_url, snapshot, "script")
    payload = runner.store.event.call_args.args[2]
    assert payload == {"snapshot_id": captured.id, "reason": "unsupported_page_target", "count": 2}
