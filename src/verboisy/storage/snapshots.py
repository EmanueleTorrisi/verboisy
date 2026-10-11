# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run-scoped capture and validated replay of persisted page snapshots.

Capture retains one transaction for the ownership check and immutable insertion.
Replay selects within the requested run before decoding the stored payload; it
never fetches a page, changes evidence or infers a replacement identifier.
"""

from __future__ import annotations

import sqlite3

from verboisy.evidence.models import Snapshot
from verboisy.storage.json_payload import decode_saved_json
from verboisy.utils.exceptions import VerboisyError


def capture_snapshot(
    db: sqlite3.Connection,
    rid: str,
    pid: int,
    page: Snapshot,
    html: str,
    visible_html: str | None,
) -> None:
    """Commit a snapshot only for a page owned by the same run."""
    with db:
        # Foreign keys establish existence, but not shared run ownership.
        if db.execute("SELECT 1 FROM pages WHERE id=? AND run_id=?", (pid, rid)).fetchone() is None:
            raise VerboisyError("Page does not belong to the requested run")
        db.execute(
            "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
            (page.id, rid, pid, page.model_dump_json(), html, visible_html or html),
        )


def validate_snapshot_page(page_run_id: str | None, run_id: str) -> None:
    """A captured page must still exist and belong to the snapshot's run.

    A snapshot foreign key cannot establish shared ownership. Check the joined
    page on every replay path, including databases opened without foreign keys.
    """
    if page_run_id != run_id:
        raise VerboisyError("Stored snapshot has no page in this run")


def load_snapshot(db: sqlite3.Connection, rid: str, snapshot_id: str) -> Snapshot | None:
    """Return an owned snapshot whose payload matches its stored identifier."""
    row = db.execute(
        "SELECT s.payload,p.run_id AS page_run_id FROM snapshots s "
        "LEFT JOIN pages p ON p.id=s.page_id WHERE s.run_id=? AND s.id=?",
        (rid, snapshot_id),
    ).fetchone()
    if row is None:
        return None
    validate_snapshot_page(row["page_run_id"], rid)
    try:
        page = Snapshot.model_validate(decode_saved_json(row["payload"]))
    except (ValueError, TypeError) as error:
        raise VerboisyError("Stored snapshot failed integrity verification") from error
    # The payload must describe the row selected by the owned identifier;
    # otherwise resume could compare evidence from a different snapshot.
    if page.id != snapshot_id:
        raise VerboisyError("Stored snapshot failed integrity verification")
    return page
