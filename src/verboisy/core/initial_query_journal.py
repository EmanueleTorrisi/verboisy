# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Invocation-scoped replay of completed initial search observations.

Validate entries before binding context and publish cache state only after its
writer succeeds. Copies isolate saved inputs, writer callbacks and replay callers.
Empty fresh searches remain retryable and are never added to durable replay state.
"""

import copy
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from verboisy.utils.exceptions import VerboisyError


@dataclass
class _QueryJournal:
    results: dict[str, dict[str, Any]]
    signatures: dict[str, str]
    write: Callable[[dict[str, Any]], None]


_current: ContextVar[_QueryJournal | None] = ContextVar("initial_query_journal", default=None)


def _validated_entry(payload: Any, *, allow_empty: bool = False) -> tuple[str, dict[str, Any], str]:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("query"), str)
        or not payload["query"].strip()
        or not isinstance(payload.get("observation"), dict)
        or not isinstance(payload["observation"].get("results"), list)
        or (not allow_empty and not payload["observation"]["results"])
    ):
        raise VerboisyError("Saved discovery result failed integrity verification")
    observation = payload["observation"]
    try:
        signature = json.dumps(observation, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise VerboisyError("Saved discovery result failed integrity verification") from error
    return payload["query"], copy.deepcopy(observation), signature


@contextmanager
def initial_query_journal(
    events: list[dict[str, Any]],
    write: Callable[[dict[str, Any]], None],
) -> Iterator[None]:
    """Bind an unambiguous acquisition cache and restore context on every exit."""
    results: dict[str, dict[str, Any]] = {}
    signatures: dict[str, str] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event, dict) else None
        query, observation, signature = _validated_entry(payload)
        if query in signatures and signatures[query] != signature:
            raise VerboisyError("Saved discovery query has conflicting results")
        results[query] = observation
        signatures[query] = signature
    journal = _QueryJournal(results, signatures, write)
    token = _current.set(journal)
    try:
        yield
    finally:
        _current.reset(token)


def replay_initial_query(query: str) -> dict[str, Any] | None:
    """Return an isolated copy of a completed observation from the bound run."""
    journal = _current.get()
    return copy.deepcopy(journal.results.get(query)) if journal is not None else None


def journal_initial_query(query: str, observation: dict[str, Any]) -> None:
    """Persist one nonempty acquisition before publishing its private replay copy."""
    journal = _current.get()
    if journal is None:
        return
    query, saved, signature = _validated_entry(
        {"query": query, "observation": observation}, allow_empty=True
    )
    if not saved["results"]:
        return
    if query in journal.signatures:
        if journal.signatures[query] != signature:
            raise VerboisyError("Saved discovery query has conflicting results")
        return
    journal.write({"query": query, "observation": copy.deepcopy(saved)})
    journal.results[query] = saved
    journal.signatures[query] = signature
