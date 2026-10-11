# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Search transports used to discover candidate public source pages."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError

from verboisy.browser.policy import validate_url
from verboisy.llm.client import LLMClient
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import (
    BudgetExceededError,
    SearchBudgetExceededError,
    SearchUnavailableError,
)

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"

MAX_RESPONSE_BYTES = 1_048_576


class SearchResult(BaseModel):
    title: str
    url: str = Field(
        min_length=1,
        max_length=8000,
    )
    description: str = ""


class SearchObservation(BaseModel):
    provider: Literal["openai", "brave"]
    query: str
    results: list[SearchResult]
    reported_tokens: int | None = None


class _Web(BaseModel):
    results: list[SearchResult]


class _BraveResponse(BaseModel):
    type: Literal["search"]
    web: _Web | None = None


def _source_results(
    payload: Any,
) -> list[SearchResult]:
    """Extract unique source URLs from OpenAI web-search output."""

    if not isinstance(payload, dict):
        return []

    found: dict[str, SearchResult] = {}

    def add(
        url: Any,
        title: Any = "",
    ) -> None:
        if not isinstance(url, str):
            return

        parsed = urlsplit(url)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return

        label = title.strip() if isinstance(title, str) and title.strip() else parsed.netloc

        if url in found:
            existing = found[url]

            if existing.title == parsed.netloc and label != parsed.netloc:
                found[url] = existing.model_copy(
                    update={
                        "title": label[:500],
                    }
                )

            return

        found[url] = SearchResult(
            title=label[:500],
            url=url,
            description="",
        )

    output = payload.get("output", [])

    if not isinstance(output, list):
        return []

    for item in output:
        if not isinstance(item, dict):
            continue

        if item.get("type") == "web_search_call":
            action = item.get("action")

            if isinstance(action, dict):
                sources = action.get("sources", [])

                if isinstance(sources, list):
                    for source in sources:
                        if not isinstance(source, dict):
                            continue

                        add(
                            source.get("url"),
                            source.get("title"),
                        )

        if item.get("type") != "message":
            continue

        content = item.get("content", [])

        if not isinstance(content, list):
            continue

        for part in content:
            if not isinstance(part, dict):
                continue

            annotations = part.get("annotations", [])

            if not isinstance(annotations, list):
                continue

            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue

                if annotation.get("type") != "url_citation":
                    continue

                add(
                    annotation.get("url"),
                    annotation.get("title"),
                )

    return list(found.values())[:10]


def _openai_search_request(query: str, config: Settings) -> dict[str, Any]:
    """Bound an individual search attempt before opening provider transport."""
    payload = {
        "model": config.openai_search_model,
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "low",
            }
        ],
        "tool_choice": "required",
        "include": [
            "web_search_call.action.sources",
        ],
        "input": (
            "Search the public web for the smallest "
            "set of high-quality sources that can "
            "satisfy this research goal efficiently. "
            "Strongly prefer authoritative pages that "
            "contain many requested records and many "
            "requested fields together in one table, "
            "list, directory, or structured page. "
            "Prefer consolidated sources over "
            "one-page-per-record browsing. Avoid "
            "social pages, user-uploaded documents, "
            "and narrow subsets unless the research "
            "goal specifically requires them. "
            "Use web search.\n\n"
            f"Research goal: {query}"
        ),
        "store": False,
    }
    payload["max_output_tokens"] = config.max_tokens
    reservation = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + config.max_tokens
    ceiling = config.model_request_budget or config.max_total_tokens
    if reservation > ceiling:
        raise BudgetExceededError("Search request budget exhausted; resume with a larger budget")
    return payload


_SEARCH_ACCOUNT: ContextVar[tuple[LLMClient, Callable[[dict[str, Any]], None]] | None] = ContextVar(
    "search_account", default=None
)


@contextmanager
def search_accounting(
    client: LLMClient, record: Callable[[dict[str, Any]], None]
) -> Iterator[None]:
    token = _SEARCH_ACCOUNT.set((client, record))
    try:
        yield
    finally:
        _SEARCH_ACCOUNT.reset(token)


def _check_search_budget(client: LLMClient | None, config: Settings) -> None:
    used = client.search_requests if client is not None else 0
    if config.search_request_budget is not None and used >= config.search_request_budget:
        raise SearchBudgetExceededError(
            "Search request budget exhausted; resume with a larger budget"
        )


async def openai_search(query: str, config: Settings) -> SearchObservation:
    """Reserve repair search against the active run before any provider request."""
    key = config.openai_api_key
    if key is None or not key.get_secret_value().strip():
        raise SearchUnavailableError("OpenAI web search requires OPENAI_API_KEY.")
    payload = _openai_search_request(query, config)
    account = _SEARCH_ACCOUNT.get()
    if account is None:
        _check_search_budget(None, config)
        return await _openai_search_transport(query, config, payload)
    client, record = account
    units = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + config.max_tokens
    details = {
        "attempt_id": str(uuid4()),
        "provider": "openai",
        "query": query,
        "model": config.openai_search_model,
        "request_units": units,
        "max_output_tokens": config.max_tokens,
    }
    try:
        _check_search_budget(client, config)
        client.reserve_request(units)
    except BudgetExceededError:
        record({**details, "status": "blocked", "reported_tokens": None})
        raise
    client.search_requests += 1
    record({**details, "status": "reserved", "reported_tokens": None})
    try:
        result = await _openai_search_transport(query, config, payload)
    except BaseException as exc:
        record(
            {
                **details,
                "status": "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                "reported_tokens": None,
                "error_type": type(exc).__name__,
            }
        )
        raise
    if result.reported_tokens is not None:
        client.report_tokens(result.reported_tokens)
    record({**details, "status": "succeeded", "reported_tokens": result.reported_tokens})
    return result


async def _openai_search_transport(
    query: str, config: Settings, payload: dict[str, Any]
) -> SearchObservation:
    key = config.openai_api_key
    assert key is not None
    try:
        async with asyncio.timeout(config.search_timeout_seconds):
            await validate_url(
                OPENAI_RESPONSES_ENDPOINT,
                config,
            )

            async with (
                httpx.AsyncClient(
                    timeout=config.search_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "POST",
                    OPENAI_RESPONSES_ENDPOINT,
                    headers={
                        "Authorization": ("Bearer " + key.get_secret_value()),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response,
            ):
                if response.status_code != 200:
                    raise SearchUnavailableError(
                        "OpenAI web search returned " f"HTTP {response.status_code}."
                    )

                body = bytearray()

                async for chunk in response.aiter_bytes():
                    body.extend(chunk)

                    if len(body) > MAX_RESPONSE_BYTES:
                        raise SearchUnavailableError(
                            "OpenAI web search response " "exceeded the size limit."
                        )

                payload = json.loads(bytes(body))

    except SearchUnavailableError:
        raise

    except (
        httpx.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise SearchUnavailableError(
            "OpenAI web search unavailable " f"({type(exc).__name__})."
        ) from None

    results = _source_results(payload)

    if not results:
        raise SearchUnavailableError("OpenAI web search returned " "no usable source URLs.")

    usage = payload.get("usage")
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    reported = (
        tokens if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0 else None
    )
    return SearchObservation(
        provider="openai",
        query=query,
        results=results,
        reported_tokens=reported,
    )


async def brave_search(
    query: str,
    config: Settings,
) -> SearchObservation:
    """Use Brave as an optional alternative search provider."""

    key = config.brave_search_api_key

    if key is None or not key.get_secret_value().strip():
        raise SearchUnavailableError("Brave Search requires " "BRAVE_SEARCH_API_KEY.")

    if len(query) > 600 or len(query.split()) > 75:
        raise SearchUnavailableError(
            "Brave Search queries must fit " "600 characters and 75 words."
        )

    account = _SEARCH_ACCOUNT.get()
    if account is None:
        _check_search_budget(None, config)
        return await _brave_search_transport(query, config)
    client, record = account
    details = {
        "attempt_id": str(uuid4()),
        "provider": "brave",
        "query": query,
        "provider_request_count": 1,
        "request_units": None,
        "reported_tokens": None,
    }
    try:
        _check_search_budget(client, config)
    except SearchBudgetExceededError:
        record({**details, "status": "blocked"})
        raise
    client.search_requests += 1
    record({**details, "status": "reserved"})
    try:
        result = await _brave_search_transport(query, config)
    except BaseException as exc:
        record(
            {
                **details,
                "status": "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                "error_type": type(exc).__name__,
            }
        )
        raise
    record({**details, "status": "succeeded"})
    return result


async def _brave_search_transport(query: str, config: Settings) -> SearchObservation:
    key = config.brave_search_api_key
    assert key is not None
    try:
        async with asyncio.timeout(config.search_timeout_seconds):
            await validate_url(
                BRAVE_ENDPOINT,
                config,
            )

            async with (
                httpx.AsyncClient(
                    timeout=config.search_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "GET",
                    BRAVE_ENDPOINT,
                    params={
                        "q": query,
                        "count": 10,
                        "result_filter": "web",
                        "text_decorations": "false",
                    },
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": (key.get_secret_value()),
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    raise SearchUnavailableError(
                        "Brave Search returned " f"HTTP {response.status_code}."
                    )

                body = bytearray()

                async for chunk in response.aiter_bytes():
                    body.extend(chunk)

                    if len(body) > MAX_RESPONSE_BYTES:
                        raise SearchUnavailableError(
                            "Brave Search response " "exceeded the size limit."
                        )

                data = _BraveResponse.model_validate_json(bytes(body))

    except SearchUnavailableError:
        raise

    except (
        httpx.HTTPError,
        TimeoutError,
        ValidationError,
    ) as exc:
        raise SearchUnavailableError(
            "Brave Search unavailable " f"({type(exc).__name__})."
        ) from None

    results = [] if data.web is None else data.web.results[:10]

    return SearchObservation(
        provider="brave",
        query=query,
        results=results,
    )


async def web_search(
    query: str,
    config: Settings,
) -> SearchObservation:
    """Select a search provider automatically."""

    provider = config.search_provider

    if provider == "disabled":
        raise SearchUnavailableError("Automatic source discovery is disabled.")

    if provider == "openai":
        if config.openai_api_key is None:
            raise SearchUnavailableError("OpenAI web search requires OPENAI_API_KEY.")

        return await openai_search(
            query,
            config,
        )

    if provider == "brave":
        if config.brave_search_api_key is None:
            raise SearchUnavailableError("Brave Search requires BRAVE_SEARCH_API_KEY.")

        return await brave_search(
            query,
            config,
        )

    # auto
    if config.openai_api_key is not None:
        try:
            return await openai_search(
                query,
                config,
            )
        except SearchUnavailableError:
            if config.brave_search_api_key is None:
                raise

    if config.brave_search_api_key is not None:
        return await brave_search(
            query,
            config,
        )

    raise SearchUnavailableError(
        "Automatic source discovery requires " "OPENAI_API_KEY or BRAVE_SEARCH_API_KEY."
    )
