# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

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


@pytest.fixture
def openai_transport(config, monkeypatch):
    """Deterministic HTTP transport for OpenAI discovery tests."""

    config.search_provider = "openai"
    config.openai_api_key = SecretStr("test-only-openai-key")

    requests = []
    original = httpx.AsyncClient

    def install(response):
        def handle(request):
            requests.append(request)

            if isinstance(response, Exception):
                raise response

            return response

        def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

            return original(
                **kwargs,
                transport=httpx.MockTransport(handle),
            )

        monkeypatch.setattr(
            "verboisy.core.search.httpx.AsyncClient",
            client,
        )

        return requests

    return install


def test_openai_source_parser_filters_invalid_sources():
    from verboisy.core.search import _source_results

    assert _source_results(None) == []
    assert _source_results({"output": "not-a-list"}) == []

    results = _source_results(
        {
            "output": [
                None,
                {
                    "type": "web_search_call",
                    "action": None,
                },
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": "not-a-list",
                    },
                },
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            None,
                            {"url": None},
                            {
                                "url": "ftp://invalid.example",
                            },
                            {
                                "url": "https://one.example/a",
                                "title": "  One  ",
                            },
                            {
                                "url": "https://one.example/a",
                                "title": "Duplicate",
                            },
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": "not-a-list",
                },
                {
                    "type": "message",
                    "content": [
                        None,
                        {
                            "annotations": "not-a-list",
                        },
                        {
                            "annotations": [
                                None,
                                {
                                    "type": "something_else",
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://two.example/b",
                                    "title": None,
                                },
                            ]
                        },
                    ],
                },
            ]
        }
    )

    assert [result.url for result in results] == [
        "https://one.example/a",
        "https://two.example/b",
    ]

    assert results[0].title == "One"
    assert results[1].title == "two.example"


def test_openai_source_parser_caps_results():
    from verboisy.core.search import _source_results

    payload = {
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {
                            "url": (f"https://example{i}.com/page"),
                            "title": f"Page {i}",
                        }
                        for i in range(12)
                    ]
                },
            }
        ]
    }

    assert len(_source_results(payload)) == 10


@pytest.mark.asyncio
async def test_openai_search_success(
    config,
    openai_transport,
):
    from verboisy.core.search import openai_search

    requests = openai_transport(
        httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [
                                {
                                    "url": "https://example.com/a",
                                    "title": "Example A",
                                }
                            ]
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.org/b",
                                        "title": "Example B",
                                    }
                                ]
                            }
                        ],
                    },
                ]
            },
        )
    )

    observation = await openai_search(
        "countries",
        config,
    )

    assert observation.provider == "openai"
    assert observation.query == "countries"

    assert [item.url for item in observation.results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]

    assert len(requests) == 1
    request = requests[0]

    assert request.method == "POST"
    assert str(request.url) == "https://api.openai.com/v1/responses"

    import json

    body = json.loads(request.content)

    assert body["tool_choice"] == "required"
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["store"] is False
    assert body["tools"][0]["type"] == "web_search"


@pytest.mark.parametrize(
    "key",
    [
        None,
        SecretStr(" "),
    ],
)
@pytest.mark.asyncio
async def test_openai_search_requires_key_before_network(
    config,
    key,
):
    from verboisy.core.search import openai_search

    config.openai_api_key = key

    with pytest.raises(
        SearchUnavailableError,
        match="OPENAI_API_KEY",
    ):
        await openai_search(
            "countries",
            config,
        )


@pytest.mark.parametrize(
    "status",
    [
        400,
        401,
        429,
        500,
    ],
)
@pytest.mark.asyncio
async def test_openai_search_http_failures_are_redacted(
    config,
    openai_transport,
    status,
):
    from verboisy.core.search import openai_search

    openai_transport(
        httpx.Response(
            status,
            text="PRIVATE PROVIDER BODY",
        )
    )

    with pytest.raises(
        SearchUnavailableError,
        match=f"HTTP {status}",
    ) as error:
        await openai_search(
            "countries",
            config,
        )

    assert "PRIVATE PROVIDER BODY" not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            text="not json SECRET",
        ),
        httpx.ConnectError("SECRET connection failure"),
        httpx.ReadTimeout("SECRET timeout"),
    ],
)
@pytest.mark.asyncio
async def test_openai_search_transport_errors_are_redacted(
    config,
    openai_transport,
    response,
):
    from verboisy.core.search import openai_search

    openai_transport(response)

    with pytest.raises(SearchUnavailableError) as error:
        await openai_search(
            "countries",
            config,
        )

    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_search_response_size_is_bounded(
    config,
    openai_transport,
):
    from verboisy.core.search import openai_search

    openai_transport(
        httpx.Response(
            200,
            content=b"x" * 1_048_577,
        )
    )

    with pytest.raises(
        SearchUnavailableError,
        match="size limit",
    ):
        await openai_search(
            "countries",
            config,
        )


@pytest.mark.asyncio
async def test_openai_search_requires_usable_sources(
    config,
    openai_transport,
):
    from verboisy.core.search import openai_search

    openai_transport(
        httpx.Response(
            200,
            json={"output": []},
        )
    )

    with pytest.raises(
        SearchUnavailableError,
        match="no usable source URLs",
    ):
        await openai_search(
            "countries",
            config,
        )


@pytest.mark.asyncio
async def test_openai_search_has_total_deadline(
    config,
    openai_transport,
    monkeypatch,
):
    import asyncio

    from verboisy.core.search import openai_search

    async def stalled(*_args):
        await asyncio.Event().wait()

    openai_transport(
        httpx.Response(
            200,
            json={"output": []},
        )
    )

    config.search_timeout_seconds = 0.01

    monkeypatch.setattr(
        "verboisy.core.search.validate_url",
        AsyncMock(side_effect=stalled),
    )

    with pytest.raises(
        SearchUnavailableError,
        match="TimeoutError",
    ):
        await openai_search(
            "countries",
            config,
        )


@pytest.mark.asyncio
async def test_web_search_provider_routing(
    config,
    monkeypatch,
):
    from verboisy.core.search import (
        SearchObservation,
        SearchResult,
        web_search,
    )

    openai_result = SearchObservation(
        provider="openai",
        query="goal",
        results=[
            SearchResult(
                title="OpenAI",
                url="https://openai.example/",
            )
        ],
    )

    brave_result = SearchObservation(
        provider="brave",
        query="goal",
        results=[
            SearchResult(
                title="Brave",
                url="https://brave.example/",
            )
        ],
    )

    openai_mock = AsyncMock(return_value=openai_result)
    brave_mock = AsyncMock(return_value=brave_result)

    monkeypatch.setattr(
        "verboisy.core.search.openai_search",
        openai_mock,
    )
    monkeypatch.setattr(
        "verboisy.core.search.brave_search",
        brave_mock,
    )

    # disabled
    config.search_provider = "disabled"

    with pytest.raises(
        SearchUnavailableError,
        match="disabled",
    ):
        await web_search("goal", config)

    # explicit OpenAI without credentials
    config.search_provider = "openai"
    config.openai_api_key = None

    with pytest.raises(
        SearchUnavailableError,
        match="OPENAI_API_KEY",
    ):
        await web_search("goal", config)

    # explicit OpenAI
    config.openai_api_key = SecretStr("openai")

    assert (await web_search("goal", config)).provider == "openai"

    # explicit Brave without credentials
    config.search_provider = "brave"
    config.brave_search_api_key = None

    with pytest.raises(
        SearchUnavailableError,
        match="BRAVE_SEARCH_API_KEY",
    ):
        await web_search("goal", config)

    # explicit Brave
    config.brave_search_api_key = SecretStr("brave")

    assert (await web_search("goal", config)).provider == "brave"

    # auto prefers OpenAI
    config.search_provider = "auto"
    config.openai_api_key = SecretStr("openai")
    config.brave_search_api_key = SecretStr("brave")

    openai_mock.side_effect = None
    openai_mock.return_value = openai_result

    assert (await web_search("goal", config)).provider == "openai"

    # auto falls back from OpenAI to Brave
    openai_mock.side_effect = SearchUnavailableError("openai unavailable")

    assert (await web_search("goal", config)).provider == "brave"

    # auto propagates OpenAI failure when no fallback exists
    config.brave_search_api_key = None

    with pytest.raises(
        SearchUnavailableError,
        match="openai unavailable",
    ):
        await web_search("goal", config)

    # auto can use Brave directly when OpenAI is not configured
    config.openai_api_key = None
    config.brave_search_api_key = SecretStr("brave")
    openai_mock.side_effect = None

    assert (await web_search("goal", config)).provider == "brave"

    # auto with no configured provider
    config.brave_search_api_key = None

    with pytest.raises(
        SearchUnavailableError,
        match="requires OPENAI_API_KEY or BRAVE_SEARCH_API_KEY",
    ):
        await web_search("goal", config)


def test_openai_sources_upgrade_host_title_from_citation():
    from verboisy.core.search import _source_results

    results = _source_results(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {"sources": [{"url": ("https://example.com/" "countries")}]},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": ("https://example.com/" "countries"),
                                    "title": ("Countries by population, " "capital and area"),
                                }
                            ]
                        }
                    ],
                },
            ]
        }
    )

    assert len(results) == 1
    assert results[0].title == ("Countries by population, capital and area")
