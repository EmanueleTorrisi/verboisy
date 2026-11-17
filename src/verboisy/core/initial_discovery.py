# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Initial source selection, durable search replay and frontier publication.

The public API retains input validation and its compatibility wrappers. Explicit
callbacks retain its current provider, URL and client hooks. This workflow borrows
the ledger and never owns browser startup, candidate extraction or output files.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from verboisy.core.discovery_replay import validated_discovery_result, validated_observation
from verboisy.core.initial_query_journal import (
    initial_query_journal,
    journal_initial_query,
    replay_initial_query,
)
from verboisy.core.metadata_discovery import MetadataSourceScope
from verboisy.core.planner import ResearchPlan
from verboisy.core.search import SearchObservation, search_accounting
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.llm.client import LLMClient
from verboisy.product import SourcePolicy
from verboisy.storage.event_journal import decode_event_rows
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import (
    BudgetExceededError,
    SearchBudgetExceededError,
    SearchUnavailableError,
    VerboisyError,
)


def _metadata_seeds(
    scope: MetadataSourceScope, query: str, observation: dict[str, Any]
) -> list[str]:
    if observation["query"] != query:
        raise VerboisyError("Saved HTML metadata discovery query does not match its task")
    return scope.select(result["url"] for result in observation["results"])


async def _discover_metadata_sources(
    goal: str,
    task: TaskSpec,
    policy: SourcePolicy,
    config: Settings,
    search: Callable[[str, Settings], Awaitable[SearchObservation]],
    canonicalize: Callable[[str], str | None],
) -> tuple[list[str], list[dict[str, Any]]]:
    scope = MetadataSourceScope.from_task(task)
    scope.check_policy(policy)
    query = scope.query(goal)
    saved = replay_initial_query(query)
    if saved is not None:
        observation = validated_observation(saved, policy, canonicalize=canonicalize)
        return _metadata_seeds(scope, query, observation), [observation]

    response = await search(query, config)
    candidates = {
        url: result.model_copy(update={"url": url}).model_dump()
        for result in response.results
        if (url := canonicalize(result.url)) is not None and scope.paths_for(url)
    }
    observation = {
        "provider": response.provider,
        "query": response.query,
        "results": list(candidates.values()),
    }
    seeds = _metadata_seeds(scope, query, observation)
    # A partial result remains retryable. A complete selection can be replayed
    # even if saving the acquisition or its frontier is interrupted.
    journal_initial_query(query, observation)
    return seeds, [observation]


def _validate_metadata_acquisition(
    goal: str,
    task: TaskSpec,
    policy: SourcePolicy,
    seeds: list[str],
    observations: list[dict[str, Any]],
) -> None:
    scope = MetadataSourceScope.from_task(task)
    scope.check_policy(policy)
    if (
        len(observations) != 1
        or seeds != _metadata_seeds(scope, scope.query(goal), observations[0])
        or (task.seed_urls and seeds != task.seed_urls)
    ):
        raise VerboisyError("Saved HTML metadata discovery does not match its selected sources")


async def discover_seed_sources(
    goal: str,
    spec: TaskSpec,
    policy: SourcePolicy,
    config: Settings,
    plan: ResearchPlan,
    search: Callable[[str, Settings], Awaitable[SearchObservation]],
    inline_urls: Callable[[str], list[str]],
    canonicalize: Callable[[str], str | None],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Select permitted seeds in their existing stable order, reusing saved queries."""

    if getattr(spec, "html_metadata_discovery", False):
        return await _discover_metadata_sources(goal, spec, policy, config, search, canonicalize)
    seeds = [url for url in spec.seed_urls if policy.permits(url)]

    metadata = getattr(spec, "html_metadata", None) is not None
    if metadata or getattr(spec, "html_table", None) is not None:
        # The literal contract names the complete observed scope. A goal URL or
        # a search result cannot silently add an entity to the task.
        if seeds != spec.seed_urls:
            kind = "metadata" if metadata else "table"
            raise VerboisyError(f"A declared HTML {kind} seed conflicts with the source policy")
        return seeds, []

    inline = inline_urls(goal)

    seeds.extend(url for url in inline if policy.permits(url))

    observations: list[dict[str, Any]] = []

    queries: list[str] = []

    for domain in policy.include:
        queries.append(f"site:{domain} {goal}")

    if not policy.onlyinclude:
        queries.append(goal)

    if policy.include or not seeds:
        for query in dict.fromkeys(queries):
            saved_observation = replay_initial_query(query)
            if saved_observation is None:
                try:
                    observation = await search(
                        query,
                        config,
                    )

                except SearchUnavailableError:
                    if not seeds:
                        raise
                    continue

                accepted = [
                    result
                    for result in observation.results
                    if (url := canonicalize(result.url)) is not None and policy.permits(url)
                ]

                accepted.sort(
                    key=lambda result: plan.source_score(
                        result.title,
                        result.url,
                    ),
                    reverse=True,
                )

                saved_observation = {
                    "provider": observation.provider,
                    "query": observation.query,
                    "results": [result.model_dump() for result in accepted],
                }
                journal_initial_query(query, saved_observation)

            saved_observation = validated_observation(
                saved_observation, policy, canonicalize=canonicalize
            )
            observations.append(saved_observation)
            seeds.extend(result["url"] for result in saved_observation["results"])

    canonical = [canonicalize(url) for url in seeds]

    return [url for url in dict.fromkeys(canonical) if url is not None], observations


def acquisition_events(store: ResearchStore, rid: str, kind: str) -> list[dict[str, Any]]:
    """Keep compatible replay until a reviewed decision requests a new acquisition."""
    change = store.db.execute(
        "SELECT MAX(id) FROM events WHERE run_id=? AND kind='initial_discovery_reset'", (rid,)
    ).fetchone()[0]
    if change is None:
        return store.events(rid, kind)
    return decode_event_rows(
        store.db.execute(
            "SELECT kind,payload,created_at FROM events "
            "WHERE run_id=? AND kind=? AND id>? ORDER BY id",
            (rid, kind, change),
        ).fetchall()
    )


def preflight_initial_discovery(
    store: ResearchStore, rid: str, policy: SourcePolicy, task: TaskSpec | None = None
) -> None:
    """Check the replay branch before resume can commit a requirement decision.

    A saved acquisition takes precedence over query checkpoints. Validate only
    the branch publication will consume, without creating clients or durable entries.
    Binding a temporary query context reuses its conflict checks and restores
    any enclosing context on exit; the writer is never invoked during replay.
    """
    results = acquisition_events(store, rid, "initial_discovery_result")
    if results:
        seeds, observations = validated_discovery_result(
            results[-1]["payload"], policy, canonicalize=canonical_url
        )
        if task is not None and task.html_metadata_discovery:
            _validate_metadata_acquisition(
                store.load(rid)["goal"], task, policy, seeds, observations
            )
    else:
        scope = None
        if task is not None and task.html_metadata_discovery:
            if task.seed_urls:
                raise VerboisyError("Selected HTML metadata sources have no saved discovery")
            scope = MetadataSourceScope.from_task(task)
            scope.check_policy(policy)
            query = scope.query(store.load(rid)["goal"])
        queries = acquisition_events(store, rid, "initial_query_result")
        unused_writes: list[dict[str, Any]] = []
        with initial_query_journal(queries, unused_writes.append):
            for event in queries:
                observation = validated_observation(
                    event["payload"]["observation"], policy, canonicalize=canonical_url
                )
                if scope is not None:
                    if event["payload"]["query"] != query:
                        raise VerboisyError(
                            "Saved HTML metadata discovery query does not match its task"
                        )
                    _metadata_seeds(scope, query, observation)


async def publish_initial_discovery(
    store: ResearchStore,
    rid: str,
    spec: TaskSpec,
    policy: SourcePolicy,
    config: Settings,
    plan: ResearchPlan,
    discover: Callable[..., Awaitable[tuple[list[str], list[dict[str, Any]]]]],
    make_client: Callable[..., LLMClient],
) -> TaskSpec:
    """Restore accounting and publish an acquisition with the existing retry checkpoints."""

    state = store.load(rid)
    client = make_client(config=config)
    client.total_tokens = state["tokens"]
    client.reserved_tokens = state["reserved"]
    client.search_requests = store.search_attempt_count(rid)
    client.on_usage = lambda: store.finish(
        rid, "RUNNING", "initial_discovery", client.total_tokens, client.reserved_tokens
    )
    try:
        saved_results = acquisition_events(store, rid, "initial_discovery_result")
        if saved_results:
            result = saved_results[-1]["payload"]
            seeds, observations = validated_discovery_result(
                result, policy, canonicalize=canonical_url
            )
        else:
            with (
                search_accounting(
                    client, lambda payload: store.event(rid, "search_request", payload)
                ),
                initial_query_journal(
                    acquisition_events(store, rid, "initial_query_result"),
                    lambda payload: store.event(rid, "initial_query_result", payload),
                ),
            ):
                seeds, observations = await discover(state["goal"], spec, policy, config, plan)
            if not seeds:
                raise VerboisyError("Source discovery found no permitted HTTP(S) seed URLs")
            seeds, observations = validated_discovery_result(
                {"seeds": seeds, "observations": observations}, policy, canonicalize=canonical_url
            )
        scoped_metadata = getattr(spec, "html_metadata_discovery", False)
        if scoped_metadata:
            _validate_metadata_acquisition(state["goal"], spec, policy, seeds, observations)
        if not saved_results:
            # Save the acquisition before publishing task/frontier state. A resume
            # can replay publication without spending another provider request.
            store.event(
                rid, "initial_discovery_result", {"seeds": seeds, "observations": observations}
            )
        metadata = getattr(spec, "html_metadata", None) is not None
        if (
            not scoped_metadata
            and (metadata or getattr(spec, "html_table", None) is not None)
            and (seeds != spec.seed_urls or observations)
        ):
            kind = "metadata" if metadata else "table"
            raise VerboisyError(f"Saved discovery differs from the declared HTML {kind} scope")
        spec = spec.model_copy(update={"seed_urls": seeds})
        store.update_task(rid, spec)
        published = [
            event["payload"] for event in acquisition_events(store, rid, "source_discovery")
        ]
        for observation in observations:
            if observation not in published:
                store.event(rid, "source_discovery", observation)
                published.append(observation)
        active, deferred = plan.split_initial_sources(seeds)
        for url in active:
            store.queue(rid, url, 0, None)
        for url in deferred:
            store.defer(rid, url, 0, None)
        store.event(
            rid,
            "seed_frontier",
            {"discovered": len(seeds), "active": len(active), "deferred": len(deferred)},
        )
    except BaseException as error:
        reason = (
            "search_request_budget"
            if isinstance(error, SearchBudgetExceededError)
            else "model_request_budget"
            if isinstance(error, BudgetExceededError)
            else "cancelled"
            if isinstance(error, asyncio.CancelledError)
            else "source_discovery_failed"
        )
        store.finish(rid, "PAUSED", reason, client.total_tokens, client.reserved_tokens)
        if isinstance(error, VerboisyError):
            error.details["run_id"] = rid
        raise
    return spec
