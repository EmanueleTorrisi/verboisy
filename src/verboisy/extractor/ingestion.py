# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit dataset ingestion with exact source values and persistent row evidence."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from verboisy.core.dataset_comparison import compare_dataset_evidence
from verboisy.core.fitness import temporal_errors
from verboisy.evidence.models import (
    Candidate,
    Snapshot,
)
from verboisy.evidence.verify import verify
from verboisy.extractor.dataset import DatasetParseError
from verboisy.extractor.dataset_evidence import _row_scope
from verboisy.extractor.dataset_evidence import row_evidence as row_evidence
from verboisy.extractor.dataset_journal import _accepted_row as _accepted_row
from verboisy.extractor.dataset_journal import _record_row as _record_row
from verboisy.extractor.dataset_journal import _restore_row_journal as _restore_row_journal
from verboisy.extractor.dataset_journal import (
    validate_dataset_evidence as validate_dataset_evidence,
)
from verboisy.extractor.download import DatasetDownloadError, download_dataset
from verboisy.extractor.local import load_local_dataset
from verboisy.extractor.profile import profile_dataset
from verboisy.extractor.projection import ProjectionError
from verboisy.storage.assets import DatasetAssetError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


def _dataset_preference(runner: ResearchRunner, page: Snapshot, candidate: Candidate) -> str | None:
    """Apply the existing dataset comparison with the caller's verification hook."""
    return compare_dataset_evidence(
        runner,
        page,
        candidate,
        lambda row, snapshot, schema, task: verify(row, snapshot, schema, task),
    )


def _dataset_target_reached(runner: ResearchRunner, count: int) -> bool:
    """Stop at the entity target unless declared identities still need metadata repair."""
    target = runner.task.target_records
    return (
        target is not None
        and count >= target
        and (not runner.task.identity_fields or not runner.dataset_consistency_gaps())
    )


async def run_dataset_sources(runner: ResearchRunner, max_steps: int) -> tuple[str, str]:
    """Acquire declared sources, replay saved assets and accept strictly supported rows.

    Each uncaptured source consumes one invocation step. Saved sources consume no
    download steps. No browser, search or model calls occur; only declared conversions are applied.
    """
    store, rid = runner.store, runner.rid
    status, reason = "PAUSED", "dataset_source_budget"
    attempts = 0
    try:
        count = len(store.records(rid))
        target = runner.task.target_records
        async with asyncio.timeout(runner.config.run_timeout_seconds):
            saved = store.dataset_assets(rid)
            profiled = {
                event["payload"]["asset_id"] for event in store.events(rid, "dataset_profile")
            }
            processed = {
                event["payload"]["snapshot_id"] for event in store.events(rid, "dataset_row")
            }
            processed.update(
                event["payload"]["row_scope"]
                for event in store.events(rid, "dataset_projection_failure")
            )
            _restore_row_journal(runner, saved, processed)
            for declared in runner.task.dataset_sources:
                if _dataset_target_reached(runner, count):
                    break
                asset = next(
                    (
                        item
                        for item in saved
                        if item.download.original_url == declared.url
                        and item.download.dataset.format == declared.format
                    ),
                    None,
                )
                if asset is None:
                    if attempts >= max_steps:
                        return status, reason
                    attempts += 1
                    if urlsplit(declared.url).scheme == "file":
                        downloaded = await load_local_dataset(
                            declared.url, runner.config, dataset_format=declared.format
                        )
                    else:
                        downloaded = await download_dataset(
                            declared.url,
                            runner.config,
                            dataset_format=declared.format,
                            permits=runner.in_scope,
                        )
                    asset_id = store.save_dataset_asset(rid, downloaded)
                    asset = store.load_dataset_asset(rid, asset_id)
                    saved.append(asset)
                if asset.id not in profiled:
                    store.event(
                        rid,
                        "dataset_profile",
                        {
                            "asset_id": asset.id,
                            "profile": asdict(profile_dataset(asset.download.dataset)),
                        },
                    )
                    profiled.add(asset.id)
                for row in asset.download.dataset.rows:
                    await asyncio.sleep(0)
                    scope = _row_scope(asset, row, declared.projection)
                    if scope in processed:
                        continue
                    try:
                        page, candidate = row_evidence(asset, row, declared.projection)
                    except ProjectionError:
                        assert declared.projection is not None
                        store.event(
                            rid,
                            "dataset_projection_failure",
                            {
                                "asset_id": asset.id,
                                "row_index": row.row_index,
                                "row_scope": scope,
                                "reason": "invalid_projection",
                                "plan": declared.projection.model_dump(),
                            },
                        )
                        processed.add(scope)
                        continue
                    if store.load_snapshot(rid, page.id) is None:
                        store.queue(rid, asset.download.final_url, 0, None)
                        work = store.db.execute(
                            "SELECT id FROM pages WHERE run_id=? AND url=?",
                            (rid, asset.download.final_url),
                        ).fetchone()
                        store.snapshot(rid, work[0], page, "", "")
                    if (
                        target is not None
                        and count >= target
                        and store.accepted_candidate_context(rid, candidate, runner.task) is None
                    ):
                        _record_row(runner, asset, row, page, "skipped", ["entity_target_reached"])
                        processed.add(page.id)
                        continue
                    reasons = verify(candidate, page, runner.schema, runner.task)
                    if candidate.temporal_evidence:
                        reasons.extend(
                            temporal_errors(
                                candidate,
                                page,
                                runner.schema,
                                runner.temporal_intent,
                                current_year=runner.current_year,
                                field_semantics=runner.field_semantics,
                            )
                        )
                    preference = (
                        _dataset_preference(runner, page, candidate)
                        if not reasons and runner.task.identity_fields
                        else None
                    )
                    record_delta: list[int] = []
                    outcome = store.accept(
                        rid,
                        page,
                        candidate,
                        reasons,
                        runner.task,
                        preference=preference,
                        record_delta=record_delta,
                    )
                    _record_row(runner, asset, row, page, outcome, reasons)
                    processed.add(page.id)
                    # Admission reports the committed insert/delete delta, including
                    # preferred replacements and identity conflicts. Keep the initial
                    # integrity scan, but never decode the growing collection per row.
                    count += record_delta[0]
                    if _dataset_target_reached(runner, count):
                        break
                store.db.execute(
                    "UPDATE pages SET status='done',reason=NULL WHERE run_id=? AND url=?",
                    (rid, asset.download.final_url),
                )
                store.db.commit()
            if runner.target_met():
                status, reason = "COMPLETED", "target_met"
            elif runner.target_record_count_met() and runner.dataset_consistency_gaps():
                reason = "dataset_consistency_gaps"
                store.event(
                    rid,
                    "dataset_consistency_gap",
                    {
                        "gaps": list(runner.dataset_consistency_gaps()),
                        "repairs": list(runner.dataset_consistency_repairs()),
                    },
                )
            elif store.summary(rid)["rejected_candidates"] or store.events(
                rid, "dataset_projection_failure"
            ):
                reason = "dataset_row_gaps"
            else:
                status, reason = "EXHAUSTED", "observed_scope_exhausted"
    except (DatasetDownloadError, DatasetParseError) as error:
        status, reason = "FAILED", "dataset_source_failure"
        store.event(rid, "dataset_source_failure", {"error_type": type(error).__name__})
    except DatasetAssetError:
        status, reason = "FAILED", "dataset_asset_integrity"
    except TimeoutError:
        reason = "run_timeout"
    except (asyncio.CancelledError, KeyboardInterrupt):
        reason = "interrupted"
        raise
    except Exception as error:
        # Unexpected execution faults are not a normal source-budget pause.
        status, reason = "FAILED", f"execution_{type(error).__name__}"
        raise
    finally:
        store.finish(rid, status, reason, runner.client.total_tokens, runner.client.reserved_tokens)
    return status, reason
