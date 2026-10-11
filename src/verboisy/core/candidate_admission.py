# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compare reviewed candidates and journal their existing ledger admission outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from verboisy.evidence.models import Candidate, Snapshot

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def admit_reviewed_candidate(
    runner: ResearchRunner,
    captured: Snapshot,
    supplied: Snapshot,
    candidate: Candidate,
    errors: list[str],
) -> str:
    """Retain comparison, acceptance and outcome-event ordering for one candidate."""
    preference = None
    comparison = None

    accepted_context = getattr(
        runner.store,
        "accepted_candidate_context",
        None,
    )
    accepted_candidate = getattr(
        runner.store,
        "accepted_candidate",
        None,
    )

    previous = None
    previous_snapshot_id = None

    if not errors and getattr(
        runner.task,
        "identity_fields",
        [],
    ):
        if callable(accepted_context):
            context = accepted_context(
                runner.rid,
                candidate,
                runner.task,
            )

            if context is not None:
                (
                    previous,
                    previous_snapshot_id,
                ) = context

        elif callable(accepted_candidate):
            previous = accepted_candidate(
                runner.rid,
                candidate,
                runner.task,
            )

    # Compare only an eligible prior identity; review errors still reach ledger rejection.
    if previous is not None:
        (
            comparison,
            comparison_mode,
        ) = runner.compare_candidate_evidence(
            previous,
            previous_snapshot_id,
            candidate,
            supplied.id,
        )

        preference = comparison.preference

        if preference != "same":
            runner.store.event(
                runner.rid,
                "candidate_comparison",
                {
                    "url": captured.url,
                    "comparison_mode": (comparison_mode),
                    **comparison.as_event(),
                },
            )

    outcome = runner.store.accept(
        runner.rid,
        captured,
        candidate,
        errors,
        runner.task,
        preference=preference,
    )
    runner.store.event(
        runner.rid,
        "candidate",
        {
            "outcome": outcome,
            "reasons": errors,
        },
    )

    return outcome
