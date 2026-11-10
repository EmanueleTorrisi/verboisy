# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bound the JSON payload read for a page within an already verified snapshot."""

import sqlite3
from contextlib import closing
from typing import Any

from verboisy.streaming.contract import StreamError
from verboisy.utils.json_payload import decode_json

MAX_PAGE_BYTES = 16 * 1024**2
_VALUE = "COALESCE(output_json,source_json)"


def page_budget(max_bytes: int | None) -> int:
    if max_bytes is None:
        return MAX_PAGE_BYTES
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 1 <= max_bytes <= MAX_PAGE_BYTES
    ):
        raise StreamError(f"Page max_bytes must be an integer from 1 to {MAX_PAGE_BYTES}")
    return max_bytes


def read_page_rows(
    db: sqlite3.Connection,
    job_id: str,
    *,
    after: int,
    limit: int,
    record_ceiling: int,
    budget: int,
    allow_short: bool,
) -> list[dict[str, Any]]:
    """Find a contiguous ordinal range before returning any payload to Python."""
    last = after
    # The primary key supplies the order and both range scans stay in the
    # caller's SQLite snapshot. Only byte lengths cross the first cursor.
    with closing(
        db.execute(
            f"SELECT ordinal,CASE WHEN typeof({_VALUE})='text' "
            f"THEN length(CAST({_VALUE} AS BLOB)) END "
            "FROM stream_rows WHERE job_id=? AND ordinal>? ORDER BY ordinal LIMIT ?",
            (job_id, after, limit),
        )
    ) as sizes:
        for ordinal, size in sizes:
            if size is None or not 0 < size <= record_ceiling:
                raise StreamError("Saved streaming page record violates its byte limit")
            if size > budget:
                if not allow_short:
                    raise StreamError(
                        "Requested streaming page exceeds its byte limit; "
                        "reduce limit or pass max_bytes to allow a shorter page"
                    )
                if last == after:
                    raise StreamError("Next verified record exceeds max_bytes; increase the budget")
                break
            budget -= size
            last = ordinal
    if last == after:
        return []
    with closing(
        db.execute(
            f"SELECT ordinal,{_VALUE} FROM stream_rows "
            "WHERE job_id=? AND ordinal>? AND ordinal<=? ORDER BY ordinal",
            (job_id, after, last),
        )
    ) as values:
        return [{"ordinal": ordinal, "record": decode_json(value)} for ordinal, value in values]
