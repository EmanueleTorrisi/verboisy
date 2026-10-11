# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepare bounded page evidence before requesting candidate proposals.

Chunking and adaptive ordering run before semantic planning. Coverage-gap writes
retain their existing order; failed writes propagate before cached failure state
is published. This workflow does not extract candidates or advance the browser.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from verboisy.evidence.models import Snapshot, Source
from verboisy.utils.exceptions import LLMResponseError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


async def prepare_page_batches(
    runner: ResearchRunner,
    captured: Snapshot,
    split_sources: Callable[[Snapshot, int], list[list[Source]]],
) -> list[list[Source]]:
    """Retain source ordering and suppress proposals after invalid semantic plans."""

    try:
        batches = split_sources(
            captured,
            runner.config.max_dom_chars,
        )

        if runner.adaptive_frontier:
            batches = runner.window_batches(batches)
            batches = runner.rank_batches(batches)

    except ValueError:
        runner.store.event(runner.rid, "coverage_gap", {"reason": "oversized_evidence_block"})
        batches = []
    if batches and not getattr(
        runner,
        "semantic_plan_failed",
        False,
    ):
        try:
            await runner.ensure_field_semantics()
        except LLMResponseError:
            runner.store.event(
                runner.rid,
                "coverage_gap",
                {"reason": "invalid_semantic_plan"},
            )
            runner.semantic_plan_failed = True
            batches = []

    if getattr(
        runner,
        "semantic_plan_failed",
        False,
    ):
        batches = []

    return batches
