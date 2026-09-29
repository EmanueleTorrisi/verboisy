"""Real HTTP client semantics with deterministic transport; no subscription is used."""

from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from verboisy.core.search import brave_search
from verboisy.utils.exceptions import NavigationError, SearchUnavailableError


@pytest.fixture
def search_transport(config, monkeypatch):
    config.search_provider = "brave"
    config.brave_search_api_key = SecretStr("test-only-key")
    requests = []
    original = httpx.AsyncClient

    def install(response):
        def handle(request):
            requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        def client(**kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
            return original(**kwargs, transport=httpx.MockTransport(handle))

        monkeypatch.setattr("verboisy.core.search.httpx.AsyncClient", client)
        return requests

    return install


@pytest.mark.parametrize(
    "payload", [{"type": "search"}, {"type": "search", "web": {"results": []}}]
)
async def test_valid_empty_search(config, search_transport, payload):
    search_transport(httpx.Response(200, json=payload))
    assert (await brave_search("no matches", config)).results == []


@pytest.mark.parametrize("status", [401, 429, 503, 302])
async def test_provider_error_and_redirect_never_fall_back(config, search_transport, status):
    requests = search_transport(
        httpx.Response(
            status, headers={"location": "https://other.example"}, text="PRIVATE RESPONSE"
        )
    )
    with pytest.raises(SearchUnavailableError, match=f"HTTP {status}") as error:
        await brave_search("startups", config)
    assert "PRIVATE RESPONSE" not in str(error.value) and len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not JSON SECRET"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"type": "search", "web": {"results": [{"url": 7}]}}),
        httpx.ConnectError("SECRET from remote"),
        httpx.ReadTimeout("SECRET timeout"),
    ],
)
async def test_malformed_and_transport_errors_are_redacted(config, search_transport, response):
    search_transport(response)
    with pytest.raises(SearchUnavailableError) as error:
        await brave_search("startups", config)
    assert "SECRET" not in str(error.value)


async def test_response_size_is_bounded(config, search_transport):
    search_transport(httpx.Response(200, content=b"x" * 1_048_577))
    with pytest.raises(SearchUnavailableError, match="size limit"):
        await brave_search("startups", config)


async def test_overlong_result_url_is_rejected_instead_of_truncated(config, search_transport):
    search_transport(
        httpx.Response(
            200,
            json={
                "type": "search",
                "web": {"results": [{"title": "Page", "url": "https://example.com/" + "x" * 8000}]},
            },
        )
    )
    with pytest.raises(SearchUnavailableError, match="ValidationError"):
        await brave_search("startups", config)


@pytest.mark.parametrize("key", [None, SecretStr(" ")])
async def test_missing_search_key_fails_before_network(config, key):
    config.brave_search_api_key = key
    with pytest.raises(SearchUnavailableError, match="BRAVE_SEARCH_API_KEY"):
        await brave_search("startups", config)


@pytest.mark.parametrize("query", ["x" * 601, "word " * 76])
async def test_brave_query_limits(config, search_transport, query):
    search_transport(httpx.Response(200, json={"type": "search"}))
    with pytest.raises(SearchUnavailableError, match="600 characters and 75 words"):
        await brave_search(query, config)


async def test_search_api_respects_network_policy(config, search_transport):
    requests = search_transport(httpx.Response(200, json={"type": "search"}))
    config.allowed_domains = ["example.com"]
    with pytest.raises(NavigationError, match="ALLOWED_DOMAINS"):
        await brave_search("startups", config)
    assert requests == []


async def test_search_has_total_deadline(config, search_transport, monkeypatch):
    import asyncio

    async def stalled(*_args):
        await asyncio.Event().wait()

    search_transport(httpx.Response(200, json={"type": "search"}))
    config.search_timeout_seconds = 0.01
    monkeypatch.setattr("verboisy.core.search.validate_url", AsyncMock(side_effect=stalled))
    with pytest.raises(SearchUnavailableError, match="TimeoutError"):
        await brave_search("startups", config)
