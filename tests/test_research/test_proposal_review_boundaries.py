# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Proposal failures and change pauses must stop before review and acceptance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.proposal_review import review_page_proposal
from verboisy.evidence.models import Candidate, PageProposal, Snapshot
from verboisy.extractor.range_changes import ProposedChangesPauseError


@pytest.mark.parametrize("stop", ["journal_failure", "range_offer"])
async def test_proposal_stop_precedes_candidate_review(stop):
    candidate = Candidate(scope="entity", record={"value": 1}, evidence={})
    proposal = PageProposal(candidates=[candidate])
    captured = Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-10-01T00:00:00Z",
        content_hash="hash",
        sources=[],
        truncated=False,
    )
    supplied = captured.model_copy(update={"sources": []})
    runner = SimpleNamespace(
        rid="run",
        store=SimpleNamespace(event=MagicMock(), accept=MagicMock()),
        extractor=SimpleNamespace(check=AsyncMock(return_value=[])),
        source_assess_candidates=AsyncMock(),
    )
    offer_range = MagicMock(return_value=object())
    conflicts = MagicMock(return_value=[])
    offer_research = MagicMock()
    if stop == "journal_failure":
        runner.store.event.side_effect = OSError("Proposal journal failed")
        expected = OSError
    else:
        expected = ProposedChangesPauseError

    with pytest.raises(expected):
        await review_page_proposal(
            runner, captured, supplied, proposal, offer_range, conflicts, offer_research
        )

    runner.store.event.assert_called_once_with(
        "run",
        "extraction_proposal",
        {"snapshot_id": captured.id, "proposal": proposal.model_dump(mode="json")},
    )
    if stop == "journal_failure":
        conflicts.assert_not_called()
        offer_range.assert_not_called()
    else:
        conflicts.assert_called_once_with(proposal)
        offer_range.assert_called_once_with(runner.store, "run", supplied, [])
    runner.extractor.check.assert_not_awaited()
    runner.source_assess_candidates.assert_not_awaited()
    runner.store.accept.assert_not_called()
    offer_research.assert_not_called()
