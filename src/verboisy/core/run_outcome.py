# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Choose the saved run outcome when no frontier work remains.

A consistency diagnostic takes precedence over source failures and unresolved
coverage. Observed scope exhaustion is never a claim of global completeness.
The caller owns target completion, budgets and final checkpoint persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def exhausted_frontier_outcome(
    runner: ResearchRunner,
    summary: dict[str, Any],
) -> tuple[str, str]:
    """Journal consistency gaps before returning their pause outcome."""

    consistency_gaps: tuple[str, ...] = ()
    records: list[dict[str, Any]] = []

    target = getattr(
        runner.task,
        "target_records",
        None,
    )
    records_method = getattr(
        runner.store,
        "records",
        None,
    )

    if target is not None and callable(records_method):
        records = records_method(runner.rid)

        if len(records) >= target:
            consistency_gaps = runner.dataset_consistency_gaps()

    if consistency_gaps:
        diagnostic: dict[str, object] = {
            "gaps": list(consistency_gaps),
            "records": len(records),
            "target_records": target,
        }

        repairs = runner.dataset_consistency_repairs()

        if repairs:
            diagnostic["repairs"] = list(repairs)

        runner.store.event(
            runner.rid,
            "dataset_consistency_gap",
            diagnostic,
        )
        status, reason = (
            "PAUSED",
            "dataset_consistency_gaps",
        )
    elif summary["pages"].get("failed"):
        status, reason = (
            "FAILED",
            "source_failures",
        )
    elif (
        summary["pages"].get("blocked") or summary["coverage_gaps"] or summary["identity_conflicts"]
    ):
        status, reason = (
            "PAUSED",
            "coverage_or_identity_gaps",
        )
    else:
        status, reason = (
            "EXHAUSTED",
            "observed_scope_exhausted",
        )

    return status, reason
