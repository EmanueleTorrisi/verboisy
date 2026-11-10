# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Plan and explicitly apply local, transactional ledger retention."""

import hashlib
import hmac
import json
import re
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from verboisy.storage.retention import (
    canonical_id,
    delete_planned,
    planned_counts,
    select_completed,
)
from verboisy.utils.exceptions import VerboisyError
from verboisy.workspace import workspace_ledger

DEFAULT_KEEP_LAST = 10
DEFAULT_LIMIT = 25


def retain_completed(
    workspace: Path,
    database: str,
    *,
    kind: str = "research",
    keep_last: int = DEFAULT_KEEP_LAST,
    limit: int = DEFAULT_LIMIT,
    protect: tuple[str, ...] = (),
    apply_plan: str | None = None,
) -> dict[str, Any]:
    """Preview by default; apply only a matching plan under the ledger writer lock.

    Newest means insertion order among completed entries, not elapsed time.
    Removal is logical and affects only the selected ledger. The plan does
    not cover exports, caches, backups or physical erasure of storage pages.
    """
    if kind not in ("research", "stream"):
        raise VerboisyError("Choose research or stream retention")
    if (
        isinstance(keep_last, bool)
        or not isinstance(keep_last, int)
        or not 0 <= keep_last <= 100_000
    ):
        raise VerboisyError("Keep-last must be an integer from 0 to 100,000")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise VerboisyError("Retention limit must be an integer from 1 to 100")
    if not isinstance(protect, tuple) or len(protect) > 100:
        raise VerboisyError("Supply at most 100 protected run or job IDs")
    protected = tuple(sorted({canonical_id(value) for value in protect}))
    if apply_plan is not None and (
        not isinstance(apply_plan, str) or re.fullmatch(r"[0-9a-f]{64}", apply_plan) is None
    ):
        raise VerboisyError("Apply requires the full SHA-256 from a retention preview")
    target = workspace_ledger(workspace, database)
    lock = (
        FileLock(str(target.path) + ".lock", timeout=0, mode=0o600) if apply_plan else nullcontext()
    )
    mode = "rw" if apply_plan else "ro"
    try:
        with lock:
            stamp = target.stamp()
            with closing(
                sqlite3.connect(
                    target.path.as_uri() + f"?mode={mode}",
                    uri=True,
                    timeout=0,
                    isolation_level=None,
                )
            ) as db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                db.execute("PRAGMA cache_size=-8192")
                db.execute("PRAGMA mmap_size=0")
                db.execute("PRAGMA temp_store=FILE")
                db.execute("BEGIN IMMEDIATE" if apply_plan else "BEGIN")
                ids, truncated = select_completed(db, kind, keep_last, protected, limit)
                counts = planned_counts(db, kind, ids)
                if target.stamp() != stamp:
                    raise VerboisyError(
                        "Ledger changed while planning retention; create a new plan"
                    )
                plan = {
                    "version": "retention-1",
                    "ledger_kind": kind,
                    "selection_order": "oldest_completed_by_insertion",
                    "keep_last_completed": keep_last,
                    "limit": limit,
                    "protected_ids": protected,
                    "selected_ids": ids,
                    "truncated": truncated,
                    "rows": counts,
                    "effect": "logical_ledger_deletion",
                }
                reviewed = json.dumps(
                    [str(target.path), stamp, plan], sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                token = hashlib.sha256(reviewed).hexdigest()
                if apply_plan is not None:
                    if not hmac.compare_digest(apply_plan, token):
                        raise VerboisyError("Retention plan changed; review a fresh preview")
                    if not ids:
                        raise VerboisyError("Retention preview has no completed entries to remove")
                    delete_planned(db, kind, ids, counts)
                    db.commit()
                return {**plan, "plan_sha256": token, "applied": apply_plan is not None}
    except Timeout:
        raise VerboisyError("Ledger is in use by another Verboisy writer") from None
    except sqlite3.Error:
        raise VerboisyError(
            "Cannot complete retention against this ledger; no deletion committed"
        ) from None
