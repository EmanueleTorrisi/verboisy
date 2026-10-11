# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Admission journal failures must retain the existing ledger write boundaries."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from verboisy.core.candidate_admission import admit_reviewed_candidate
from verboisy.evidence.models import Candidate, Snapshot


@pytest.mark.parametrize("failed_event", ["candidate_comparison", "candidate"])
def test_admission_write_failure_preserves_acceptance_order(failed_event):
    captured = Snapshot(
        id="captured",
        url="https://example.test/",
        fetched_at="2026-10-01T00:00:00Z",
        content_hash="hash",
        sources=[],
        truncated=False,
    )
    supplied = captured.model_copy(update={"id": "supplied"})
    candidate = Candidate(scope="new", record={"name": "Alba"}, evidence={})
    previous = Candidate(scope="old", record={"name": "Alba"}, evidence={})
    errors = []
    writes = []

    def journal(rid, kind, payload):
        writes.append(kind)
        if kind == failed_event:
            raise OSError("Admission journal failed")

    def accept(*args, **kwargs):
        writes.append("accept")
        return "accepted"

    comparison = SimpleNamespace(
        preference="new", as_event=MagicMock(return_value={"preference": "new"})
    )
    runner = SimpleNamespace(
        rid="run",
        task=SimpleNamespace(identity_fields=["/name"]),
        store=SimpleNamespace(
            accepted_candidate_context=MagicMock(return_value=(previous, "prior")),
            event=MagicMock(side_effect=journal),
            accept=MagicMock(side_effect=accept),
        ),
        compare_candidate_evidence=MagicMock(return_value=(comparison, "quality")),
    )

    with pytest.raises(OSError, match="Admission journal failed"):
        admit_reviewed_candidate(runner, captured, supplied, candidate, errors)

    runner.compare_candidate_evidence.assert_called_once_with(
        previous, "prior", candidate, supplied.id
    )
    if failed_event == "candidate_comparison":
        assert writes == ["candidate_comparison"]
        runner.store.accept.assert_not_called()
    else:
        assert writes == ["candidate_comparison", "accept", "candidate"]
        runner.store.accept.assert_called_once_with(
            "run", captured, candidate, errors, runner.task, preference="new"
        )
