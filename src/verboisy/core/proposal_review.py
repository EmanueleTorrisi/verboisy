# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Journal and review extraction proposals before candidate acceptance."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import ValidationError

from verboisy.evidence.models import Candidate, PageProposal, RangeConflict, Snapshot
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.extractor.proof_preparation import prepare_candidate_proofs
from verboisy.extractor.range_changes import ProposedChangesPauseError
from verboisy.utils.exceptions import LLMResponseError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


async def review_page_proposal(
    runner: ResearchRunner,
    captured: Snapshot,
    supplied: Snapshot,
    proposal: PageProposal,
    offer_range: Callable[..., object | None],
    range_conflicts: Callable[[PageProposal], list[RangeConflict]],
    offer_research: Callable[..., object | None],
) -> list[tuple[Candidate, list[str]]]:
    """Keep current-contract review and grounded change offers ahead of acceptance."""
    if isinstance(proposal, PageProposal):
        runner.store.event(
            runner.rid,
            "extraction_proposal",
            {
                "snapshot_id": captured.id,
                "proposal": proposal.model_dump(mode="json"),
            },
        )
        if offer_range(runner.store, runner.rid, supplied, range_conflicts(proposal)) is not None:
            raise ProposedChangesPauseError
    checked_candidates: list[tuple[Candidate, list[str]]] = []

    for candidate_index, candidate in enumerate(proposal.candidates):
        if isinstance(runner.extractor, EvidenceExtractor):
            prepared, changes = prepare_candidate_proofs(
                candidate, supplied, runner.extractor.task, runner.extractor.field_semantics
            )
            if changes:
                runner.store.event(
                    runner.rid,
                    "evidence_preparation",
                    {
                        "snapshot_id": captured.id,
                        "candidate_index": candidate_index,
                        "changes": changes,
                        "candidate": prepared.model_dump(mode="json"),
                    },
                )
            candidate = prepared
        try:
            errors = await runner.extractor.check(
                candidate,
                supplied,
            )
        except ValidationError:
            errors = ["invalid_review"]
        except LLMResponseError:
            runner.store.event(
                runner.rid,
                "coverage_gap",
                {"reason": ("invalid_review_response")},
            )
            errors = ["invalid_review"]

        checked_candidates.append(
            (
                candidate,
                errors,
            )
        )

    verified_candidates = [candidate for candidate, errors in checked_candidates if not errors]

    # Valid current-contract data takes priority over alternatives. Only
    # offer a broader change after this batch yields no qualifying row.
    if (
        not verified_candidates
        and isinstance(proposal, PageProposal)
        and offer_research(runner.store, runner.rid, supplied, proposal.research_suggestions)
        is not None
    ):
        raise ProposedChangesPauseError

    if verified_candidates:
        await runner.source_assess_candidates(
            supplied,
            verified_candidates,
        )

    return checked_candidates
