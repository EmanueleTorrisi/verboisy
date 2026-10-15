# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validate saved evidence without queries, writes or historical payload rewriting."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from typing import Any

from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.storage.json_payload import copy_saved_json, decode_saved_json
from verboisy.storage.snapshots import validate_snapshot_page
from verboisy.utils.exceptions import VerboisyError

Encoder = Callable[[Any], str]
IdentityLookup = Callable[[dict[str, Any], str], Any]


def _validate_accepted_reference(row: sqlite3.Row, run_id: str) -> None:
    """Reject incomplete or foreign evidence chains before comparison or export."""
    if row["candidate_id"] is None:
        raise VerboisyError("Selected record has no candidate")
    # Foreign keys establish existence, not ownership or accepted disposition.
    if row["run_id"] != run_id:
        raise VerboisyError("Accepted candidate belongs to another run")
    if row["accepted"] != 1:
        raise VerboisyError("Stored accepted candidate failed integrity verification")
    if row["snapshot_run_id"] != run_id:
        raise VerboisyError("Accepted candidate has no snapshot in this run")
    validate_snapshot_page(row["page_run_id"], run_id)


def _validated_snapshot_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Check the captured model and reference without rewriting historical JSON."""
    try:
        payload: dict[str, Any] = decode_saved_json(row["snapshot"])
        page = Snapshot.model_validate(payload)
    except (ValueError, TypeError) as error:
        raise VerboisyError("Stored snapshot failed integrity verification") from error
    if page.id != row["snapshot_id"]:
        raise VerboisyError("Stored snapshot failed integrity verification")
    return payload


def _validate_selected_record(row: sqlite3.Row, record: dict[str, Any], *, encode: Encoder) -> None:
    """A selected row must retain the accepted candidate's raw values."""
    try:
        selected_payload = encode(decode_saved_json(row["record_payload"]))
        accepted_payload = encode(record)
    except (ValueError, TypeError) as error:
        raise VerboisyError("Selected record payload differs from accepted candidate") from error
    if selected_payload != accepted_payload:
        raise VerboisyError("Selected record payload differs from accepted candidate")


def validated_accepted_candidate(
    row: sqlite3.Row,
    run_id: str,
    task: TaskSpec,
    identity: str,
    *,
    encode: Encoder,
    lookup: IdentityLookup,
) -> Candidate:
    """Reject damaged selected references before comparison can use their evidence."""
    _validate_accepted_reference(row, run_id)
    try:
        candidate = Candidate.model_validate(decode_saved_json(row["payload"]))
    except (ValueError, TypeError) as error:
        raise VerboisyError("Stored accepted candidate failed integrity verification") from error
    if "id" in candidate.record:
        raise VerboisyError(
            "Saved source-ID contract is incompatible; create a new run projected to source_id"
        )
    # The selected key comes from the requested identity. A structurally valid
    # payload must still refer to that entity, including every compound field.
    try:
        saved_identity = encode(
            [lookup(candidate.record, pointer) for pointer in task.identity_fields]
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise VerboisyError("Accepted candidate identity differs from selected record") from error
    if saved_identity != identity:
        raise VerboisyError("Accepted candidate identity differs from selected record")
    _validated_snapshot_payload(row)
    _validate_selected_record(row, candidate.record, encode=encode)
    return candidate


def decode_evidence_rows(
    rows: list[sqlite3.Row],
    rid: str,
    task: TaskSpec,
    *,
    encode: Encoder,
    lookup: IdentityLookup,
) -> list[dict[str, Any]]:
    """Validate selected rows while retaining their original decoded JSON shape."""
    result = []
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        _validate_accepted_reference(row, rid)
        try:
            candidate = decode_saved_json(row["payload"])
            validated = Candidate.model_validate(candidate)
        except (ValueError, TypeError) as error:
            raise VerboisyError(
                "Stored accepted candidate failed integrity verification"
            ) from error
        if "id" in validated.record:
            raise VerboisyError(
                "Saved source-ID contract is incompatible; create a new run projected to source_id"
            )
        # Reproduce admission's key from raw candidate identity, before any
        # presentation or unit normalization of public output values.
        try:
            identity = (
                encode([lookup(validated.record, pointer) for pointer in task.identity_fields])
                if task.identity_fields
                else encode(validated.record)
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise VerboisyError(
                "Evidence candidate identity differs from selected record"
            ) from error
        if hashlib.sha256(identity.encode()).hexdigest() != row["identity"]:
            raise VerboisyError("Evidence candidate identity differs from selected record")
        # Key by both reference and exact saved JSON: a different historical
        # shape or damaged payload must never inherit an earlier validation.
        snapshot_key = (row["snapshot_id"], row["snapshot"])
        if snapshot_key not in snapshots:
            snapshots[snapshot_key] = _validated_snapshot_payload(row)
        snapshot_payload = copy_saved_json(snapshots[snapshot_key])
        _validate_selected_record(row, candidate["record"], encode=encode)
        # Validate models without replacing historical payloads with dumps:
        # optional defaults must not change the portable evidence's shape.
        result.append(
            {
                "row_index": index,
                "record_id": row["stable_id"],
                "candidate": candidate,
                "snapshot": snapshot_payload,
            }
        )
    return result
