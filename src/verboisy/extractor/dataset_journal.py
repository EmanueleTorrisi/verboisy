# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Replay accepted dataset bindings and recover missing row journal entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.extractor.dataset import SourceRow
from verboisy.extractor.dataset_evidence import row_evidence
from verboisy.storage.assets import DatasetAssetError, StoredDatasetAsset
from verboisy.utils.exceptions import VerboisyError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner
    from verboisy.storage.research import ResearchStore


def _record_row(
    runner: ResearchRunner,
    asset: StoredDatasetAsset,
    row: SourceRow,
    page: Snapshot,
    outcome: str,
    reasons: list[str],
) -> None:
    runner.store.event(
        runner.rid,
        "dataset_row",
        {
            "asset_id": asset.id,
            "snapshot_id": page.id,
            "row_index": row.row_index,
            "source_pointer": row.source_pointer,
            "line_start": row.line_start,
            "line_end": row.line_end,
            "outcome": outcome,
            "reasons": reasons,
        },
    )


def _accepted_row(
    task: TaskSpec, by_id: dict[str, StoredDatasetAsset], context: dict[str, Any]
) -> tuple[StoredDatasetAsset, SourceRow, Snapshot]:
    page = Snapshot.model_validate(context["snapshot"])
    if page.dataset_asset_id is None:
        raise DatasetAssetError("Accepted dataset row has no captured source")
    asset = by_id.get(page.dataset_asset_id)
    index = page.dataset_row_index
    if asset is None or index is None or index > len(asset.download.dataset.rows):
        raise DatasetAssetError("Accepted dataset row has no captured source")
    row = asset.download.dataset.rows[index - 1]
    if not any(
        declared.url == asset.download.original_url
        and declared.format == asset.download.dataset.format
        and declared.projection == page.dataset_projection
        for declared in task.dataset_sources
    ):
        raise DatasetAssetError("Accepted projection differs from saved declarations")
    expected_page, expected_candidate = row_evidence(asset, row, page.dataset_projection)
    if (
        page != expected_page
        or Candidate.model_validate(context["candidate"]) != expected_candidate
    ):
        raise DatasetAssetError("Accepted dataset row differs from its captured source")
    return asset, row, page


def _accepted_contexts(store: ResearchStore, rid: str) -> list[dict[str, Any]]:
    """Keep dataset resume's integrity error category when ledger checks fail early."""
    try:
        return store.evidence(rid)
    except VerboisyError as error:
        raise DatasetAssetError("Accepted dataset row cannot verify its captured source") from error


def validate_dataset_evidence(store: ResearchStore, rid: str, task: TaskSpec) -> None:
    """Verify accepted bindings on completed resume without changing the journal."""
    # Completion does not bypass evidence checks: verify persisted bindings against
    # saved assets without downloading again or rewriting the event journal.
    assets = {asset.id: asset for asset in store.dataset_assets(rid)}
    for context in _accepted_contexts(store, rid):
        _accepted_row(task, assets, context)


def _restore_row_journal(
    runner: ResearchRunner, assets: list[StoredDatasetAsset], processed: set[str]
) -> None:
    """Validate accepted bindings and restore missing row journal entries."""
    by_id = {asset.id: asset for asset in assets}
    for context in _accepted_contexts(runner.store, runner.rid):
        checked = _accepted_row(runner.task, by_id, context)
        asset, row, page = checked
        if page.id in processed:
            continue
        _record_row(runner, asset, row, page, "accepted", [])
        runner.store.db.execute(
            "UPDATE pages SET status='done',reason=NULL WHERE run_id=? AND url=?",
            (runner.rid, page.url),
        )
        runner.store.db.commit()
        processed.add(page.id)
