# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Versioned evidence ledger, single writer, stable records, and resumable state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from verboisy.core.source_assessment import claim_comparability_from_events
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.verify import lookup
from verboisy.extractor.download import DownloadedDataset
from verboisy.storage.admission import admit_candidate
from verboisy.storage.assets import StoredDatasetAsset, list_assets, load_asset, save_asset
from verboisy.storage.event_journal import decode_event_rows, reserved_attempt_ids
from verboisy.storage.frontier_selection import select_frontier_page
from verboisy.storage.json_payload import decode_saved_json
from verboisy.storage.ledger_schema import initialize_ledger, validate_ledger_identity
from verboisy.storage.record_view import _apply_unit_normalizations as _apply_unit_normalizations
from verboisy.storage.record_view import _replace_pointer_value as _replace_pointer_value
from verboisy.storage.record_view import normalized_record_view
from verboisy.storage.saved_evidence import decode_evidence_rows
from verboisy.storage.saved_evidence import (
    validated_accepted_candidate as _validated_accepted_candidate,
)
from verboisy.storage.snapshots import capture_snapshot, load_snapshot
from verboisy.utils.exceptions import VerboisyError

DB_VERSION = 4


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _stable_row_id(run_id: str, identity: str) -> str:
    """Generate an opaque stable row ID from persisted run and identity keys."""

    return uuid.uuid5(uuid.NAMESPACE_URL, f"verboisy:{run_id}:{identity}").hex


class ResearchStore:
    def __init__(self, path: str, *, read_only: bool = False):
        if read_only:
            requested = Path(path)
            if requested.is_symlink() or not requested.is_file():
                raise VerboisyError("Choose an existing research database")
            self.path = requested.resolve()
            self.lock = FileLock(str(self.path) + ".lock")
            try:
                self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            except sqlite3.Error:
                raise VerboisyError("Cannot open the research database for inspection") from None
            try:
                self.db.row_factory = sqlite3.Row
                self.db.execute("BEGIN")
                tables = {
                    row[0]
                    for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                validate_ledger_identity(self.db, tables)
                versions = self.db.execute("SELECT version FROM research_meta").fetchall()
                if len(versions) != 1 or versions[0]["version"] != DB_VERSION:
                    raise VerboisyError("Repair inspection requires the current ledger version")
            except BaseException as error:
                self.close()
                if isinstance(error, sqlite3.Error):
                    raise VerboisyError("Not a readable current research ledger") from None
                raise
            return
        if Path(path).exists() and not Path(path).is_file():
            raise VerboisyError("Research ledger must be a regular file")
        if Path(path).is_symlink():
            raise VerboisyError("Research ledger must not be a symlink")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise VerboisyError("Database is in use by another run") from None
        try:
            self.db = sqlite3.connect(self.path)
        except sqlite3.Error:
            self.lock.release()
            raise VerboisyError("Cannot open research ledger") from None
        except BaseException:
            self.lock.release()
            raise
        try:
            self.db.row_factory = sqlite3.Row
            tables = {
                r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "runs" in tables and "research_runs" not in tables:
                raise VerboisyError(
                    "Legacy database: preserve it and choose a new SQLITE_DB_PATH. "
                    "Legacy records are unverified."
                )
            validate_ledger_identity(self.db, tables)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self._initialize_or_migrate(tables)
        except sqlite3.Error:
            self.close()
            raise VerboisyError("Not a readable research ledger") from None
        except BaseException:
            self.close()
            raise

    def _initialize_or_migrate(self, tables: set[str]) -> None:
        initialize_ledger(
            self.db,
            tables,
            current_version=DB_VERSION,
            stable_row_id=_stable_row_id,
        )

    def save_dataset_asset(self, rid: str, download: DownloadedDataset) -> str:
        return save_asset(self.db, rid, download)

    def load_dataset_asset(self, rid: str, asset_id: str) -> StoredDatasetAsset:
        return load_asset(self.db, rid, asset_id)

    def dataset_assets(self, rid: str) -> list[StoredDatasetAsset]:
        return list_assets(self.db, rid)

    def create(self, goal: str, schema: dict[str, Any], task: TaskSpec, export: str | None) -> str:
        rid = str(uuid.uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO research_runs(id,goal,schema_json,task_json,status,export_path) "
                "VALUES(?,?,?,?,?,?)",
                (rid, goal, encode(schema), task.model_dump_json(), "RUNNING", export),
            )
        return rid

    def update_task(self, rid: str, task: TaskSpec) -> None:
        """Persist discovered seeds before handing the run to the research runner."""
        with self.db:
            self.db.execute(
                "UPDATE research_runs SET task_json=? WHERE id=?",
                (task.model_dump_json(), rid),
            )

    def load(self, rid: str | None) -> dict[str, Any]:
        rows = (
            self.db.execute("SELECT * FROM research_runs WHERE id=?", (rid,)).fetchall()
            if rid
            else self.db.execute(
                "SELECT * FROM research_runs WHERE status!='COMPLETED' ORDER BY rowid DESC LIMIT 1"
            ).fetchall()
        )
        if len(rows) != 1:
            raise VerboisyError(f"No saved research run found in {self.path}")
        state = dict(rows[0])
        # Validate before callers apply saved decisions or publish new work.
        # Keep the original JSON text: decoding must not rewrite history.
        for field in ("schema_json", "task_json"):
            try:
                if not isinstance(decode_saved_json(state[field]), dict):
                    raise ValueError("Saved requirements must be JSON objects")
            except (ValueError, TypeError):
                label = "task" if field == "task_json" else "schema"
                raise VerboisyError(f"Saved {label} failed integrity verification") from None
        return state

    def event(self, rid: str, kind: str, value: Any) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)", (rid, kind, encode(value))
            )

    def events(self, rid: str, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is None:
            rows = self.db.execute(
                "SELECT kind,payload,created_at FROM events WHERE run_id=? ORDER BY id", (rid,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT kind,payload,created_at FROM events WHERE run_id=? AND kind=? ORDER BY id",
                (rid, kind),
            ).fetchall()
        return decode_event_rows(rows)

    def search_attempt_count(self, rid: str) -> int:
        """Count durable reservations, including failed and cancelled attempts."""
        return len(reserved_attempt_ids(self.events(rid, "search_request")))

    def queue(self, rid: str, url: str, depth: int, parent: str | None) -> None:
        """Queue justified work, promoting it if it was previously deferred."""

        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO pages(run_id,url,depth,parent_url) VALUES(?,?,?,?)",
                (rid, url, depth, parent),
            )
            self.db.execute(
                "UPDATE pages SET status='queued',reason=NULL "
                "WHERE run_id=? AND url=? AND status='deferred'",
                (rid, url),
            )

    def defer(self, rid: str, url: str, depth: int, parent: str | None) -> None:
        """Persist lower-value work without putting it on the active frontier."""

        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO "
                "pages(run_id,url,depth,parent_url,status) "
                "VALUES(?,?,?,?, 'deferred')",
                (rid, url, depth, parent),
            )

    def queue_repair(
        self,
        rid: str,
        url: str,
        depth: int,
        parent: str | None,
    ) -> None:
        """Queue exact dataset-repair work ahead of generic frontier work."""

        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO "
                "pages(run_id,url,depth,parent_url,status) "
                "VALUES(?,?,?,?, 'repair')",
                (
                    rid,
                    url,
                    depth,
                    parent,
                ),
            )
            self.db.execute(
                "UPDATE pages "
                "SET status='repair',reason=NULL "
                "WHERE run_id=? AND url=? "
                "AND status IN ('queued','deferred')",
                (
                    rid,
                    url,
                ),
            )

    def next_page(
        self,
        rid: str,
        host_scores: Mapping[str, float] | None = None,
    ) -> dict[str, Any] | None:
        """Choose useful frontier work while preserving deterministic fallbacks."""

        scores = host_scores or {}

        def candidates(status: str) -> list[Any]:
            rows = self.db.execute(
                "SELECT * FROM pages WHERE run_id=? AND status=? ORDER BY depth,id",
                (rid, status),
            ).fetchall()

            if not rows:
                return []

            minimum_depth = rows[0]["depth"]

            return [row for row in rows if row["depth"] == minimum_depth]

        with self.db:
            repair = candidates("repair")
            queued = candidates("queued")
            deferred = candidates("deferred")

            row = select_frontier_page(repair, queued, deferred, scores)
            if row is None:
                return None

            self.db.execute(
                "UPDATE pages SET status='active',reason=? WHERE id=?",
                (
                    ("dataset_repair" if row["status"] == "repair" else None),
                    row["id"],
                ),
            )

            return dict(row)

    def rebalance_frontier(
        self,
        rid: str,
        active_limit: int,
    ) -> dict[str, int]:
        """Demote legacy queued overflow without discarding work."""

        rows = self.db.execute(
            "SELECT id FROM pages WHERE run_id=? AND status='queued' ORDER BY depth,id",
            (rid,),
        ).fetchall()

        kept = min(
            len(rows),
            active_limit,
        )
        overflow = rows[active_limit:]

        with self.db:
            self.db.executemany(
                "UPDATE pages SET status='deferred' WHERE id=?",
                [(row["id"],) for row in overflow],
            )

        return {
            "queued": kept,
            "demoted": len(overflow),
        }

    def recover(self, rid: str) -> None:
        # Only interrupted active work is requeued. Committed rows and completed pages
        # remain intact, and repair work retains its distinct scheduling state.
        with self.db:
            self.db.execute(
                "UPDATE pages "
                "SET status=CASE "
                "WHEN reason='dataset_repair' "
                "THEN 'repair' "
                "ELSE 'queued' "
                "END,reason=NULL "
                "WHERE run_id=? AND status='active'",
                (rid,),
            )

    def mark_page(self, pid: int, status: str, reason: str | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE pages SET status=?,reason=? WHERE id=?", (status, reason, pid))

    def snapshot(
        self, rid: str, pid: int, page: Snapshot, html: str, visible_html: str | None = None
    ) -> None:
        capture_snapshot(self.db, rid, pid, page, html, visible_html)

    def load_snapshot(self, rid: str, snapshot_id: str) -> Snapshot | None:
        """Load a snapshot only from the requested run."""
        return load_snapshot(self.db, rid, snapshot_id)

    def accepted_candidate(
        self,
        rid: str,
        candidate: Candidate,
        task: TaskSpec,
    ) -> Candidate | None:
        """Return the currently accepted candidate for this identity."""

        if not task.identity_fields:
            return None

        identity = encode([lookup(candidate.record, pointer) for pointer in task.identity_fields])
        key = hashlib.sha256(identity.encode()).hexdigest()

        row = self.db.execute(
            """
            SELECT c.id AS candidate_id, c.payload, c.run_id, c.accepted,
                   s.run_id AS snapshot_run_id, s.payload AS snapshot, p.run_id AS page_run_id,
                   r.payload AS record_payload, s.id AS snapshot_id
            FROM records r
            LEFT JOIN candidates c
              ON c.id = r.candidate_id
            LEFT JOIN snapshots s
              ON s.id = c.snapshot_id
            LEFT JOIN pages p ON p.id = s.page_id
            WHERE r.run_id=?
              AND r.identity=?
            """,
            (rid, key),
        ).fetchone()

        if row is None:
            return None

        return _validated_accepted_candidate(row, rid, task, identity, encode=encode, lookup=lookup)

    def accepted_candidate_context(
        self,
        rid: str,
        candidate: Candidate,
        task: TaskSpec,
    ) -> tuple[Candidate, str] | None:
        """Return accepted candidate and its originating snapshot."""

        if not task.identity_fields:
            return None

        identity = encode(
            [
                lookup(
                    candidate.record,
                    pointer,
                )
                for pointer in task.identity_fields
            ]
        )

        key = hashlib.sha256(identity.encode()).hexdigest()

        row = self.db.execute(
            """
            SELECT c.id AS candidate_id, c.payload, c.snapshot_id, c.run_id, c.accepted,
                   s.run_id AS snapshot_run_id, s.payload AS snapshot, p.run_id AS page_run_id,
                   r.payload AS record_payload
            FROM records r
            LEFT JOIN candidates c
              ON c.id = r.candidate_id
            LEFT JOIN snapshots s
              ON s.id = c.snapshot_id
            LEFT JOIN pages p ON p.id = s.page_id
            WHERE r.run_id = ?
              AND r.identity = ?
            """,
            (
                rid,
                key,
            ),
        ).fetchone()

        if row is None:
            return None

        return (
            _validated_accepted_candidate(row, rid, task, identity, encode=encode, lookup=lookup),
            str(row["snapshot_id"]),
        )

    def accept(
        self,
        rid: str,
        page: Snapshot,
        candidate: Candidate,
        reasons: list[str],
        task: TaskSpec,
        *,
        preference: str | None = None,
        record_delta: list[int] | None = None,
    ) -> str:
        """Admit normally and optionally report the committed record-count change.

        The caller receives the delta only after the admission transaction commits.
        Inserts, duplicates, replacements and conflict deletions retain their usual
        disposition strings. No record payloads are decoded just to count rows.
        """
        delta = [0]
        outcome = admit_candidate(
            self.db,
            rid,
            page,
            candidate,
            reasons,
            task,
            preference=preference,
            encode=encode,
            lookup=lookup,
            stable_row_id=_stable_row_id,
            record_delta=delta,
        )
        if record_delta is not None:
            record_delta[:] = delta
        return outcome

    def records(self, rid: str) -> list[dict[str, Any]]:
        """Return a grounded effective view without modifying source evidence."""
        return self.evidence_records(rid)[1]

    def evidence_records(self, rid: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read validated evidence and effective records once for one operation."""

        normalization_events = self.events(rid, "unit_normalization")
        if not normalization_events:
            # Raw views require the same evidence integrity as normalized views.
            # Keep the original row query to retain field ordering and JSON values.
            evidence = self.evidence(rid)
            rows = self.db.execute(
                "SELECT stable_id,payload FROM records WHERE run_id=? ORDER BY id", (rid,)
            ).fetchall()
            return evidence, [
                {"id": row["stable_id"], **json.loads(row["payload"])} for row in rows
            ]
        source_events = self.events(rid, "source_fitness")
        evidence = self.evidence(rid)
        return evidence, normalized_record_view(
            evidence,
            source_events,
            normalization_events,
            claim_comparability_from_events=claim_comparability_from_events,
        )

    def finish(self, rid: str, status: str, reason: str, tokens: int, reserved: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE research_runs SET status=?,reason=?,tokens=?,reserved=? WHERE id=?",
                (status, reason, tokens, reserved, rid),
            )

    def evidence(self, rid: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT r.stable_id,r.identity,r.payload AS record_payload,"
            "c.id AS candidate_id,c.run_id,c.accepted,c.payload,"
            "s.id AS snapshot_id,s.run_id AS snapshot_run_id,s.payload AS snapshot,"
            "p.run_id AS page_run_id FROM records r "
            "LEFT JOIN candidates c ON r.candidate_id=c.id "
            "LEFT JOIN snapshots s ON c.snapshot_id=s.id "
            "LEFT JOIN pages p ON p.id=s.page_id "
            "WHERE r.run_id=? ORDER BY r.id",
            (rid,),
        ).fetchall()
        if not rows:
            return []
        try:
            task = TaskSpec.model_validate_json(self.load(rid)["task_json"])
        except ValueError as error:
            raise VerboisyError("Saved task failed integrity verification") from error
        # Preserve selected rows through the joins: an incomplete evidence chain
        # must fail before export, rather than silently disappearing from proof.
        return decode_evidence_rows(rows, rid, task, encode=encode, lookup=lookup)

    def pages(self, rid: str) -> list[dict[str, Any]]:
        """Return persisted page outcomes for proof and diagnostics."""

        rows = self.db.execute(
            "SELECT url,parent_url,depth,status,reason FROM pages WHERE run_id=? ORDER BY id",
            (rid,),
        ).fetchall()
        return [dict(row) for row in rows]

    def summary(self, rid: str) -> dict[str, Any]:
        pages = {
            row[0]: row[1]
            for row in self.db.execute(
                "SELECT status,COUNT(*) FROM pages WHERE run_id=? GROUP BY status", (rid,)
            )
        }
        rejected = self.db.execute(
            "SELECT COUNT(*) FROM candidates WHERE run_id=? AND accepted=0", (rid,)
        ).fetchone()[0]
        gaps = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE run_id=? AND kind='coverage_gap'", (rid,)
        ).fetchone()[0]
        conflicts = self.db.execute(
            "SELECT COUNT(*) FROM conflicts WHERE run_id=?", (rid,)
        ).fetchone()[0]
        return {
            "pages": pages,
            "rejected_candidates": rejected,
            "coverage_gaps": gaps,
            "identity_conflicts": conflicts,
        }

    def close(self) -> None:
        # A failed connection close must not strand the application writer lease.
        # The database error still propagates after the lock release is attempted.
        try:
            self.db.close()
        finally:
            self.lock.release()
