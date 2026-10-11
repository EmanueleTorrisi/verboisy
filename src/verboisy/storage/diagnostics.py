# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read-only inspection of current dataset evidence and repair policy."""

import sqlite3
from pathlib import Path
from typing import Any

from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.ingestion import validate_dataset_evidence
from verboisy.storage.json_payload import decode_saved_json
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def inspect_dataset_repairs(database: Path, run_id: str, *, limit: int = 100) -> dict[str, Any]:
    """Replay captured bindings and report current gaps; never execute the runner."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise VerboisyError("Repair inspection limit must be an integer from 1 to 1000")
    store = ResearchStore(str(database), read_only=True)
    try:
        state = store.load(run_id)
        settings_options: dict[str, Any] = {"_env_file": None, "search_provider": "disabled"}
        runner = ResearchRunner(store, run_id, Settings(**settings_options))
        if not runner.task.dataset_sources:
            raise VerboisyError("Choose a run with declared dataset sources")
        validate_dataset_evidence(store, run_id, runner.task)
        gaps = list(runner.dataset_consistency_gaps())
        repairs = list(runner.dataset_consistency_repairs())
        return {
            "inspection_version": "1",
            "run_id": run_id,
            "status": state["status"],
            "stop_reason": state["reason"],
            "scope": "accepted_records",
            "gaps": gaps,
            "repair_count": len(repairs),
            "limit": limit,
            "truncated": len(repairs) > limit,
            "repairs": repairs[:limit],
        }
    except (sqlite3.Error, ValueError, KeyError, TypeError):
        raise VerboisyError("Saved research ledger has invalid dataset repair context") from None
    finally:
        store.close()


def inspect_research_runs(database: Path, *, limit: int = 100) -> dict[str, Any]:
    """List recent runs and declaration eligibility, without verifying or executing them."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise VerboisyError("Run inspection limit must be an integer from 1 to 1000")
    store = ResearchStore(str(database), read_only=True)
    try:
        rows = store.db.execute(
            "SELECT id, goal, status, reason, task_json FROM research_runs "
            "ORDER BY rowid DESC LIMIT ?",
            (limit + 1,),
        ).fetchall()
        runs = []
        for row in rows[:limit]:
            try:
                task = TaskSpec.model_validate(decode_saved_json(row["task_json"]))
                source_count = len(task.dataset_sources)
                eligibility = "available" if source_count else "no_dataset_sources"
            except (ValueError, TypeError):
                source_count = None
                eligibility = "invalid_task"
            runs.append(
                {
                    "run_id": row["id"],
                    "goal": row["goal"],
                    "status": row["status"],
                    "stop_reason": row["reason"],
                    "dataset_source_count": source_count,
                    "repair_inspection": eligibility,
                }
            )
        return {
            "inspection_version": "1",
            "database": str(store.path),
            "limit": limit,
            "truncated": len(rows) > limit,
            "runs": runs,
        }
    except sqlite3.Error:
        raise VerboisyError("Saved research ledger has invalid run inventory") from None
    finally:
        store.close()


def inspect_research_status(database: Path, run_id: str) -> dict[str, Any]:
    """Report persisted progress for any run; do not replay evidence or resume work."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise VerboisyError("Choose a nonempty saved run ID")
    store = ResearchStore(str(database), read_only=True)
    try:
        state = store.load(run_id)
        counts = {
            table: store.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            for table in ("records", "candidates", "snapshots", "dataset_assets", "events")
        }
        summary = store.summary(run_id)
        return {
            "inspection_version": "1",
            "database": str(store.path),
            "run_id": state["id"],
            "goal": state["goal"],
            "status": state["status"],
            "stop_reason": state["reason"],
            "scope": "persisted_run",
            "counts": {
                "accepted_records": counts["records"],
                "candidates": counts["candidates"],
                "rejected_candidates": summary["rejected_candidates"],
                "snapshots": counts["snapshots"],
                "dataset_assets": counts["dataset_assets"],
                "events": counts["events"],
                "identity_conflicts": summary["identity_conflicts"],
                "coverage_gap_events": summary["coverage_gaps"],
            },
            "page_outcomes": summary["pages"],
            "request_accounting": {
                "reported_tokens": state["tokens"],
                "reserved_request_units": state["reserved"],
                "journaled_search_attempts": store.search_attempt_count(run_id),
            },
        }
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        raise VerboisyError("Saved research ledger has invalid run status context") from None
    finally:
        store.close()
