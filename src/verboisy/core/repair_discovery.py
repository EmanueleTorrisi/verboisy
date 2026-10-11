# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Discover narrow repair sources using a borrowed ledger and shared search budget.

The runner owns invocation lifetime and supplies its scope and provider callbacks.
This workflow journals retry outcomes and queues source work; it does not accept
candidates, decide completion, close the ledger or alter the requested schema.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import cast

from verboisy.core.search import SearchObservation, search_accounting
from verboisy.evidence.models import Candidate
from verboisy.evidence.snapshot import canonical_url
from verboisy.evidence.verify import lookup
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError


async def discover_repair_source(
    store: ResearchStore,
    rid: str,
    get_client: Callable[[], LLMClient],
    get_config: Callable[[], Settings],
    identity_fields: tuple[str, ...],
    repairs: tuple[dict[str, object], ...],
    attempts: set[str],
    in_scope: Callable[[str], bool],
    search: Callable[[str, Settings], Awaitable[SearchObservation]],
) -> bool:
    """Attempt one eligible repair, preserving durable and per-invocation guards."""
    attempted: set[str] = set()
    failures: dict[str, int] = {}

    for event in store.events(
        rid,
        "dataset_repair_discovery",
    ):
        payload = event.get("payload")

        if not isinstance(
            payload,
            dict,
        ):
            continue

        key = payload.get("key")

        if isinstance(key, str):
            if payload.get("status") == "unavailable":
                failures[key] = failures.get(key, 0) + 1
            else:
                attempted.add(key)

    evidence_rows = store.evidence(rid)

    for repair in repairs:
        candidate_index = cast(
            int,
            repair["candidate_index"],
        )

        candidate = Candidate.model_validate(evidence_rows[candidate_index]["candidate"])

        identity_values = [
            str(
                lookup(
                    candidate.record,
                    pointer,
                )
            )
            for pointer in identity_fields
        ]

        pointer = cast(
            str,
            repair["pointer"],
        )

        fingerprint = {
            "record_id": repair["record_id"],
            "pointer": pointer,
            "target_mode": repair["target_mode"],
            "target_year": repair["target_year"],
            "identity": identity_values,
        }

        if repair["target_mode"] in {"unit", "definition", "methodology"}:
            fingerprint.update(
                {
                    "candidate_key": repair["candidate_key"],
                    "snapshot_id": repair["snapshot_id"],
                }
            )

        key = hashlib.sha256(
            json.dumps(
                fingerprint,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()

        # One attempt per runner; at most three unavailable attempts across resumes.
        if key in attempted or key in attempts or failures.get(key, 0) >= 3:
            continue
        attempts.add(key)

        field_term = pointer.strip("/").replace("~1", "/").replace("~0", "~").replace("/", " ")

        target_year = repair.get("target_year")

        period_term = (
            str(target_year)
            if isinstance(
                target_year,
                int,
            )
            else "latest"
        )

        query = " ".join(
            [
                *identity_values,
                field_term,
                {
                    "unit": "unit measurement scale",
                    "definition": "definition scope methodology",
                    "methodology": "measurement method methodology",
                }.get(str(repair["target_mode"]), period_term),
            ]
        )

        # Deferred access preserves no-search operation for empty or exhausted repairs.
        try:
            with search_accounting(
                get_client(),
                lambda payload: store.event(rid, "search_request", payload),
            ):
                observation = await search(
                    query,
                    get_config(),
                )

        except SearchUnavailableError as exc:
            store.event(
                rid,
                "dataset_repair_discovery",
                {
                    **fingerprint,
                    "key": key,
                    "query": query,
                    "status": "unavailable",
                    "error": str(exc),
                    "queued": [],
                },
            )

            return False

        queued: list[str] = []

        for result in observation.results:
            url = canonical_url(result.url)

            if url is None or not in_scope(url) or url in queued:
                continue

            queued.append(url)

            # Keep repair expansion narrow.
            if len(queued) >= 3:
                break

        queue_repair = getattr(
            store,
            "queue_repair",
            None,
        )

        queue_method = queue_repair if callable(queue_repair) else store.queue

        for url in queued:
            queue_method(
                rid,
                url,
                0,
                None,
            )

        store.event(
            rid,
            "dataset_repair_discovery",
            {
                **fingerprint,
                "key": key,
                "query": query,
                "provider": observation.provider,
                "status": ("queued" if queued else "empty"),
                "queued": queued,
            },
        )

        return bool(queued)

    return False
