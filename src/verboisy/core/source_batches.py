# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic entity windows and stable evidence-batch ordering.

Callbacks supply accepted counts and the current plan's scoring policy. This
module does not own a ledger, browser, model client or research-run lifecycle.
The source objects are borrowed; windowing and ranking never rewrite evidence.
"""

import json
from collections.abc import Callable

from verboisy.evidence.models import Source


def window_source_batches(
    batches: list[list[Source]],
    target: int | None,
    accepted_count: Callable[[], int],
    evidence_score: Callable[[str, int], int],
) -> list[list[Source]]:
    """Split only genuinely large batches into target-aware entity windows."""

    if target is None:
        return batches

    remaining = max(
        target - accepted_count(),
        1,
    )
    scope_limit = min(
        20,
        max(
            5,
            remaining * 2,
        ),
    )

    windows: list[list[Source]] = []
    fallback: list[list[Source]] = []

    for batch in batches:
        groups: dict[str, list[Source]] = {}
        scope_order: list[str] = []

        for source in batch:
            if source.scope not in groups:
                groups[source.scope] = []
                scope_order.append(source.scope)

            groups[source.scope].append(source)

        entity_scopes = [scope for scope in scope_order if scope != "page"]

        # Preserve existing behavior for ordinary pages. Windowing is an
        # optimization for genuinely large repeated-record structures.
        if len(entity_scopes) <= scope_limit:
            windows.append(batch)
            continue

        page_sources = groups.get("page", [])
        context_candidates: list[tuple[int, int, Source]] = []

        for index, source in enumerate(page_sources):
            value = source.text.strip()

            if not value or len(value) > 160:
                continue

            score = evidence_score(
                value,
                1,
            )

            context_candidates.append(
                (
                    score,
                    index,
                    source,
                )
            )

        context_candidates.sort(
            key=lambda item: (
                -item[0],
                item[1],
            )
        )
        context = [source for _, _, source in context_candidates[:8]]

        entity_groups = [groups[scope] for scope in entity_scopes]

        # Rich scopes are more likely to represent records than navigation
        # items containing only one source. Stable sorting preserves DOM
        # order within each class.
        entity_groups.sort(key=lambda group: len(group) < 2)

        for offset in range(
            0,
            len(entity_groups),
            scope_limit,
        ):
            window = list(context)

            for group in entity_groups[offset : offset + scope_limit]:
                window.extend(group)

            windows.append(window)

        if page_sources:
            fallback.append(page_sources)

    return windows + fallback


def rank_source_batches(
    batches: list[list[Source]],
    evidence_score: Callable[[str, int], int],
) -> list[list[Source]]:
    """Put likely high-value evidence first without dropping anything."""

    scored: list[tuple[int, int, list[Source]]] = []

    for index, batch in enumerate(batches):
        evidence = json.dumps(
            [
                source.model_dump(
                    mode="json",
                    exclude_none=True,
                )
                for source in batch
            ],
            ensure_ascii=False,
            sort_keys=True,
        )

        score = evidence_score(
            evidence,
            len(batch),
        )

        scope_counts: dict[str, int] = {}

        for source in batch:
            if source.scope == "page":
                continue

            scope_counts[source.scope] = scope_counts.get(source.scope, 0) + 1

        structured_scopes = sum(count >= 2 for count in scope_counts.values())
        score += min(structured_scopes, 10) * 100

        scored.append(
            (
                score,
                index,
                batch,
            )
        )

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    return [batch for _, _, batch in scored]
