# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded, value-free accounting from persisted search and cache events."""

import sqlite3
from collections import Counter
from typing import Any

from verboisy.storage.json_payload import decode_saved_json

MAX_EVENTS = 20_000
MAX_EVENT_BYTES = 65_536
TERMINAL = ("succeeded", "failed", "cancelled")
SEARCH_OUTCOMES = (*TERMINAL, "blocked", "unconfirmed")
JOURNAL_COUNTERS = (
    "search_attempts_reserved",
    *(f"search_attempts_{status}" for status in SEARCH_OUTCOMES),
    "cache_lookup_hits",
    "cache_lookup_misses",
    "cache_lookup_other",
    "cache_stores",
    "cache_store_other",
)


def summarize_journal(
    db: sqlite3.Connection, run_ids: tuple[str, ...]
) -> tuple[str, dict[str, dict[str, int]]]:
    """Read only bounded accounting events; do not report partial sums as totals."""
    counters = {rid: dict.fromkeys(JOURNAL_COUNTERS, 0) for rid in run_ids}
    attempts: dict[str, dict[str, str]] = {rid: {} for rid in run_ids}
    params = ",".join("?" for _ in run_ids)
    rows = db.execute(
        "SELECT run_id,kind,CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END "
        f"FROM events WHERE run_id IN ({params}) AND kind IN ('search_request','persistent_cache') "
        "ORDER BY id LIMIT ?",
        (MAX_EVENT_BYTES, *run_ids, MAX_EVENTS + 1),
    )
    try:
        for index, (rid, kind, raw) in enumerate(rows):
            if index == MAX_EVENTS:
                return "event_limit", {}
            payload = decode_saved_json(raw)
            if not isinstance(payload, dict):
                raise ValueError("Invalid accounting event")
            if kind == "search_request":
                _search(attempts[rid], payload)
            else:
                _cache(counters[rid], payload)
    except (TypeError, ValueError):
        return "invalid_event", {}
    finally:
        rows.close()

    for rid, by_attempt in attempts.items():
        outcomes = Counter(by_attempt.values())
        counters[rid]["search_attempts_reserved"] = len(by_attempt) - outcomes["blocked"]
        for status in SEARCH_OUTCOMES:
            counters[rid][f"search_attempts_{status}"] = outcomes[status]
    return "complete", counters


def _search(attempts: dict[str, str], payload: dict[str, Any]) -> None:
    attempt, status = payload.get("attempt_id"), payload.get("status")
    if not isinstance(attempt, str) or not 1 <= len(attempt) <= 128:
        raise ValueError("Invalid search attempt identity")
    old = attempts.get(attempt)
    if status == "reserved" and old != "blocked":
        attempts.setdefault(attempt, "unconfirmed")
    elif status == "blocked" and old in (None, "blocked"):
        attempts[attempt] = "blocked"
    elif status in TERMINAL and old in ("unconfirmed", status):
        attempts[attempt] = status
    else:
        raise ValueError("Inconsistent search attempt journal")


def _cache(counts: dict[str, int], payload: dict[str, Any]) -> None:
    version, outcome = payload.get("version"), payload.get("outcome")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != 1
        or payload.get("stage") != "source_assessment"
        or not isinstance(outcome, str)
    ):
        raise ValueError("Invalid cache accounting event")
    operation = payload.get("operation")
    if operation == "lookup":
        key = {"hit": "cache_lookup_hits", "miss": "cache_lookup_misses"}.get(
            outcome, "cache_lookup_other"
        )
    elif operation == "store":
        key = "cache_stores" if outcome == "stored" else "cache_store_other"
    else:
        raise ValueError("Invalid cache accounting operation")
    counts[key] += 1
