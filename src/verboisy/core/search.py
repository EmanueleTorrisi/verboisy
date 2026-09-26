"""Optional supported search transport. Results are discovery leads, not extracted records."""

import asyncio
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from verboisy.browser.policy import validate_url
from verboisy.core.state import SearchObservation, SearchResult
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_RESPONSE_BYTES = 1_048_576


class _Web(BaseModel):
    results: list[SearchResult]


class _Response(BaseModel):
    type: Literal["search"]
    web: _Web | None = None


async def brave_search(query: str, config: Settings) -> SearchObservation:
    key = config.brave_search_api_key
    if key is None or not key.get_secret_value().strip():
        raise SearchUnavailableError("Brave Search requires BRAVE_SEARCH_API_KEY.")
    if len(query) > 600 or len(query.split()) > 75:
        raise SearchUnavailableError("Brave Search queries must fit 600 characters and 75 words.")
    try:
        async with asyncio.timeout(config.search_timeout_seconds):
            await validate_url(BRAVE_ENDPOINT, config)
            async with (
                httpx.AsyncClient(
                    timeout=config.search_timeout_seconds, follow_redirects=False, trust_env=False
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
                        "X-Subscription-Token": key.get_secret_value(),
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    raise SearchUnavailableError(
                        f"Brave Search returned HTTP {response.status_code}; check the key, "
                        "plan or quota before resuming. No browser-search fallback was attempted."
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise SearchUnavailableError(
                            "Brave Search response exceeded the size limit."
                        )
                data = _Response.model_validate_json(bytes(body))
    except (httpx.HTTPError, TimeoutError, ValidationError) as exc:
        raise SearchUnavailableError(
            f"Brave Search unavailable ({type(exc).__name__}); no usable results were obtained."
        ) from None
    results = [] if data.web is None else data.web.results[:10]
    return SearchObservation(
        query=query,
        results=[
            SearchResult(title=r.title[:500], url=r.url, description=r.description[:1500])
            for r in results
        ],
    )
