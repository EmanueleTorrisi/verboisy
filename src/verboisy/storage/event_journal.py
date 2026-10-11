# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Decode saved decisions before replay or publication can consume their values."""

from __future__ import annotations

import sqlite3
from typing import Any

from verboisy.storage.json_payload import decode_saved_json
from verboisy.utils.exceptions import VerboisyError


def decode_event_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Retain event order and JSON shape, rejecting ambiguous or non-finite JSON."""
    result = []
    for row in rows:
        try:
            payload = decode_saved_json(row["payload"])
        except (ValueError, TypeError) as error:
            # Do not include saved text: event payloads may contain private inputs.
            raise VerboisyError("Saved event payload failed integrity verification") from error
        result.append({"kind": row["kind"], "payload": payload, "created_at": row["created_at"]})
    return result


def reserved_attempt_ids(events: list[dict[str, Any]], *, provider: str | None = None) -> set[str]:
    """Count reservations once; terminal and blocked entries do not consume twice."""
    attempts = set()
    for event in events:
        payload = event["payload"]
        if not isinstance(payload, dict):
            raise ValueError("Saved search request payload must be an object")
        if provider is not None and payload.get("provider") != provider:
            continue
        if payload.get("status") == "reserved" and isinstance(payload.get("attempt_id"), str):
            attempts.add(payload["attempt_id"])
    return attempts
