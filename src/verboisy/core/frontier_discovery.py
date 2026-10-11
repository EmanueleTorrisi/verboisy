# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Queue scoped page links and retain lower-value links as durable fallback work."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from verboisy.evidence.models import Snapshot

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def frontier_batch_size(runner: ResearchRunner) -> int:
    """Return a bounded expansion budget based on remaining dataset work."""
    target = cast(int, runner.task.target_records)
    remaining = max(target - len(runner.store.records(runner.rid)), 1)
    return min(runner.task.max_links_per_page, max(runner.plan.initial_source_goal, remaining * 3))


def discover_frontier(
    runner: ResearchRunner,
    page: Snapshot,
    depth: int,
    priorities: list[str],
    *,
    productive: bool = True,
) -> None:
    """Persist useful links now and lower-value links as fallback work."""
    priority_ids = set(priorities)
    urls = list(
        dict.fromkeys(
            s.href
            for s in sorted(page.sources, key=lambda s: s.id not in priority_ids)
            if s.href and runner.in_scope(s.href)
        )
    )
    candidates = urls[: runner.task.max_links_per_page]
    if runner.adaptive_frontier:
        # Ordinary traversal needs neither a remaining-record count nor a plan budget.
        budget = runner.frontier_batch_size()
        if productive:
            active = candidates[:budget]
        else:
            active = list(
                dict.fromkeys(
                    s.href
                    for s in page.sources
                    if s.id in priority_ids and s.href and runner.in_scope(s.href)
                )
            )[:budget]
        active_set = set(active)
        for url in active:
            runner.store.queue(runner.rid, url, depth + 1, page.url)
        deferred = [url for url in candidates if url not in active_set]
        for url in deferred:
            runner.store.defer(runner.rid, url, depth + 1, page.url)
        # Publish the summary only after both sets of frontier writes succeed.
        runner.store.event(
            runner.rid,
            "frontier_policy",
            {
                "page": page.id,
                "productive": productive,
                "queued": len(active),
                "deferred": len(deferred),
                "budget": budget,
            },
        )
    else:
        for url in candidates:
            runner.store.queue(runner.rid, url, depth + 1, page.url)
    if len(urls) > runner.task.max_links_per_page or page.truncated:
        runner.store.event(
            runner.rid, "coverage_gap", {"page": page.id, "reason": "snapshot_or_link_limit"}
        )
