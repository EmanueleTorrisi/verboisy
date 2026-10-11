# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic ranking of already selected crawl-frontier candidates.

The ledger supplies each scheduling state's shallowest rows and owns activation.
This module ranks those inputs without querying, changing or admitting URLs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


def select_frontier_page(
    repair: list[Any],
    queued: list[Any],
    deferred: list[Any],
    scores: Mapping[str, float],
) -> Any:
    """Preserve repair priority, productive work and deterministic ID tie breaks."""

    def score(row: Any) -> float:
        host = (urlsplit(row["url"]).hostname or "").lower().rstrip(".")

        return scores.get(host, 0.0)

    row = None
    best_queued = None

    if repair:
        row = max(
            repair,
            key=lambda candidate: (
                score(candidate),
                -candidate["id"],
            ),
        )

    if row is None and queued:
        best_queued = max(
            queued,
            key=lambda candidate: (
                score(candidate),
                -candidate["id"],
            ),
        )

        # Neutral or productive justified work remains ahead
        # of fallback work. Known-negative work may yield to
        # a deferred alternative.
        if not deferred or score(best_queued) >= 0:
            row = best_queued

    if row is None and deferred:
        row = max(
            deferred,
            key=lambda candidate: (
                score(candidate),
                -candidate["id"],
            ),
        )

    if row is None:
        row = best_queued

    return row
