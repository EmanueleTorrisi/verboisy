# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check the complete literal table selection before admitting its grounded rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from verboisy.core.candidate_admission import admit_reviewed_candidate
from verboisy.evidence.html_table import HtmlTableSpec
from verboisy.evidence.html_table_snapshot import html_table_candidates
from verboisy.evidence.models import Snapshot
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.extractor.schema_cache import validate_record

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def admit_html_table(
    runner: ResearchRunner, work: dict[str, Any], captured: Snapshot, plan: HtmlTableSpec
) -> None:
    candidates = html_table_candidates(captured, plan)
    try:
        for candidate in candidates:
            validate_record(candidate.record, runner.schema)
        valid = runner.schema.get("type") != "array" or SchemaBuilder.validator(
            runner.schema
        ).is_valid([row.record for row in candidates])
    except (ValueError, TypeError):
        valid = False
    if not valid:
        runner.store.event(
            runner.rid,
            "coverage_gap",
            {"reason": "html_table_schema", "snapshot_id": captured.id},
        )
        runner.store.mark_page(work["id"], "failed", "html_table_schema")
        return

    accepted = rejected = duplicates = 0
    for candidate in candidates:
        outcome = admit_reviewed_candidate(runner, captured, captured, candidate, [])
        accepted += int(outcome == "accepted")
        rejected += int(outcome == "rejected")
        duplicates += int(outcome == "duplicate")
    runner.record_source_productivity(
        work["url"], accepted=accepted, rejected=rejected, duplicates=duplicates
    )
    runner.store.mark_page(work["id"], "done")
