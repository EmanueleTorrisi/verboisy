# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay source yield and publish cached totals after durable marginal events."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def replay_source_productivity(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Accumulate current-requirement marginal events in their saved order."""
    totals: dict[str, dict[str, int]] = {}
    for event in events:
        payload = event["payload"]
        host = payload["host"]
        stats = totals.setdefault(host, {"accepted": 0, "misses": 0})
        stats["accepted"] += payload["accepted"]
        stats["misses"] += payload["misses"]
    return totals


def productivity_scores(
    totals: dict[str, dict[str, int]], score: Callable[[int, int], float]
) -> dict[str, float]:
    """Project cached counts through the caller's existing source-yield formula."""
    return {host: score(stats["accepted"], stats["misses"]) for host, stats in totals.items()}


def journal_source_productivity(
    runner: ResearchRunner,
    url: str,
    *,
    accepted: int,
    rejected: int,
    duplicates: int,
    score: Callable[[int, int], float],
) -> None:
    """Persist marginal yield before making its cumulative totals visible."""
    misses = rejected + duplicates
    if accepted == 0 and misses == 0:
        return
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host:
        return

    previous = runner.source_productivity.get(host, {"accepted": 0, "misses": 0})
    next_accepted = previous["accepted"] + accepted
    next_misses = previous["misses"] + misses
    runner.store.event(
        runner.rid,
        "source_productivity",
        {
            "host": host,
            "accepted": accepted,
            "misses": misses,
            "score": score(next_accepted, next_misses),
        },
    )
    # Failed writes must not create a host or alter a previously published total.
    stats = runner.source_productivity.setdefault(host, {"accepted": 0, "misses": 0})
    stats["accepted"] = next_accepted
    stats["misses"] = next_misses
