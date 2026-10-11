# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Describe accepted coverage without turning absence into a global claim."""

from typing import Any


def summarize_fields(
    rows: list[dict[str, Any]], fields: list[str]
) -> tuple[dict[str, Any], list[str]]:
    counts = {name: sum(row.get(name) is not None for row in rows) for name in fields}
    empty = [name for name, count in counts.items() if count == 0] if rows else []
    notices = []
    if empty:
        names = ", ".join(empty[:5])
        notices.append(
            f"* No accepted row supplies a non-null value for: {names}. "
            "This concerns the saved observations, not all possible sources. "
            "Inspect evidence and requirements before changing or removing these columns."
        )
    return {"scope": "accepted_records", "row_count": len(rows), "non_null_counts": counts}, notices
