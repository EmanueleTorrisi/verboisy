# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Atomic candidate admission, conflict disposition and preferred replacement.

Admission owns one transaction spanning the candidate journal, selected record
and conflict history. The store supplies its current identity helpers so the
entry point retains the same encoding and pointer semantics.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from typing import Any

from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.storage.json_payload import decode_saved_json
from verboisy.storage.saved_evidence import decode_evidence_rows
from verboisy.storage.snapshots import validate_snapshot_page
from verboisy.utils.exceptions import VerboisyError


def admit_candidate(
    db: sqlite3.Connection,
    rid: str,
    page: Snapshot,
    candidate: Candidate,
    reasons: list[str],
    task: TaskSpec,
    *,
    preference: str | None,
    encode: Callable[[Any], str],
    lookup: Callable[[dict[str, Any], str], Any],
    stable_row_id: Callable[[str, str], str],
    record_delta: list[int],
) -> str:
    """Commit a complete admission decision or roll back every related mutation."""
    payload = encode(candidate.record)
    identity = (
        encode([lookup(candidate.record, p) for p in task.identity_fields])
        if task.identity_fields and not reasons
        else payload
    )
    key = hashlib.sha256(identity.encode()).hexdigest()
    stable_id = stable_row_id(
        rid,
        key,
    )

    # Identity lookup, candidate disposition and the selected record must commit
    # together; a resume must never see half of an acceptance decision.
    with db:
        saved = db.execute(
            "SELECT s.payload,p.run_id AS page_run_id FROM snapshots s "
            "LEFT JOIN pages p ON p.id=s.page_id WHERE s.id=? AND s.run_id=?",
            (page.id, rid),
        ).fetchone()
        if saved is None:
            raise VerboisyError("Snapshot does not belong to the requested run")
        validate_snapshot_page(saved["page_run_id"], rid)
        # Most admissions use the exact captured payload. Historical JSON may
        # differ in formatting or omit optional defaults, so compare models
        # only when the serialized fast path does not match.
        if saved["payload"] != page.model_dump_json():
            try:
                persisted = Snapshot.model_validate(decode_saved_json(saved["payload"]))
            except (ValueError, TypeError) as error:
                raise VerboisyError("Stored snapshot failed integrity verification") from error
            if persisted != page:
                raise VerboisyError("Snapshot differs from its persisted evidence")
        previous = db.execute(
            """
                SELECT r.payload AS record_payload,r.identity,c.payload,
                       c.id AS candidate_id,r.stable_id,c.run_id,c.accepted,
                       s.id AS snapshot_id,s.run_id AS snapshot_run_id,s.payload AS snapshot,
                       p.run_id AS page_run_id
                FROM records r
                LEFT JOIN candidates c ON c.id=r.candidate_id
                LEFT JOIN snapshots s ON s.id=c.snapshot_id
                LEFT JOIN pages p ON p.id=s.page_id
                WHERE r.run_id=?
                  AND r.identity=?
                """,
            (rid, key),
        ).fetchone()

        # Reuse the portable-evidence checks before any disposition write. A
        # preferred replacement must not silently erase damaged saved history.
        previous_payload = None
        if previous is not None:
            saved_evidence = decode_evidence_rows(
                [previous], rid, task, encode=encode, lookup=lookup
            )
            # The decoder already proves that the selected row retains these raw
            # values. Compare canonical values, not historical JSON formatting.
            previous_payload = encode(saved_evidence[0]["candidate"]["record"])

        blocked = db.execute(
            """
                SELECT 1
                FROM conflicts
                WHERE run_id=?
                  AND identity=?
                """,
            (rid, key),
        ).fetchone()

        if not reasons and blocked:
            reasons = ["identity_conflict"]

        different = previous_payload is not None and previous_payload != payload

        # A previously accepted candidate is provably better.
        # Keep it and persist the newcomer as a rejected stale
        # candidate without poisoning the identity.
        if not reasons and different and preference == "old":
            reasons = ["superseded_candidate"]

        # The newcomer is provably better. Persist it and replace
        # the old candidate atomically while preserving the
        # record identity and stable row ID.
        if not reasons and previous is not None and preference == "new":
            cur = db.execute(
                """
                    INSERT INTO candidates(
                        run_id,
                        snapshot_id,
                        payload,
                        reasons,
                        accepted
                    )
                    VALUES(?,?,?,?,?)
                    """,
                (
                    rid,
                    page.id,
                    candidate.model_dump_json(),
                    encode([]),
                    1,
                ),
            )

            db.execute(
                """
                    UPDATE candidates
                    SET accepted=0,
                        reasons=?
                    WHERE id=?
                    """,
                (
                    encode(["superseded_candidate"]),
                    previous["candidate_id"],
                ),
            )

            db.execute(
                """
                    UPDATE records
                    SET payload=?,
                        candidate_id=?
                    WHERE run_id=?
                      AND identity=?
                    """,
                (
                    payload,
                    cur.lastrowid,
                    rid,
                    key,
                ),
            )

            db.execute(
                """
                    INSERT INTO events(
                        run_id,
                        kind,
                        payload
                    )
                    VALUES(?,?,?)
                    """,
                (
                    rid,
                    "candidate_superseded",
                    encode(
                        {
                            "stable_id": previous["stable_id"],
                            "previous_candidate_id": previous["candidate_id"],
                            "replacement_candidate_id": cur.lastrowid,
                        }
                    ),
                ),
            )

            return "accepted"

        # Anything not demonstrably ordered remains a genuine
        # conflict exactly as before.
        if not reasons and different:
            db.execute(
                """
                    INSERT OR IGNORE
                    INTO conflicts
                    VALUES(?,?)
                    """,
                (rid, key),
            )

            db.execute(
                """
                    UPDATE candidates
                    SET accepted=0,
                        reasons=?
                    WHERE id IN (
                        SELECT candidate_id
                        FROM records
                        WHERE run_id=?
                          AND identity=?
                    )
                    """,
                (
                    encode(["identity_conflict"]),
                    rid,
                    key,
                ),
            )

            removed = db.execute(
                """
                    DELETE FROM records
                    WHERE run_id=?
                      AND identity=?
                    """,
                (rid, key),
            )

            record_delta[0] -= removed.rowcount
            reasons = ["identity_conflict"]

        cur = db.execute(
            """
                INSERT INTO candidates(
                    run_id,
                    snapshot_id,
                    payload,
                    reasons,
                    accepted
                )
                VALUES(?,?,?,?,?)
                """,
            (
                rid,
                page.id,
                candidate.model_dump_json(),
                encode(reasons),
                int(not reasons),
            ),
        )

        if reasons:
            return "rejected"

        inserted = db.execute(
            """
                INSERT OR IGNORE INTO records(
                    run_id,
                    identity,
                    stable_id,
                    payload,
                    candidate_id
                )
                VALUES(?,?,?,?,?)
                """,
            (
                rid,
                key,
                stable_id,
                payload,
                cur.lastrowid,
            ),
        )

        record_delta[0] += inserted.rowcount
        return "duplicate" if previous else "accepted"
