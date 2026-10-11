# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""An oversized OpenAI search attempt never reaches provider transport."""

import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from verboisy import arun
from verboisy.core.search import _openai_search_request, openai_search, web_search
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError


def config(**updates):
    return Settings(
        _env_file=None, openai_api_key="offline-fixture-key", search_provider="openai", **updates
    )


@pytest.mark.parametrize("limits", [{"model_request_budget": 1}, {"max_total_tokens": 1}])
async def test_search_budget_checked_before_dns_and_transport(limits):
    transport = Mock(side_effect=AssertionError("Unexpected transport"))
    dns = AsyncMock(side_effect=AssertionError("Unexpected DNS"))
    with (
        patch("verboisy.core.search.httpx.AsyncClient", transport),
        patch("verboisy.core.search.validate_url", dns),
        pytest.raises(BudgetExceededError, match="Search request budget"),
    ):
        await openai_search("Find universities", config(**limits))
    transport.assert_not_called()
    dns.assert_not_awaited()


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_exact_utf8_request_boundary(offset):
    settings = config(max_tokens=64)
    body = _openai_search_request("Anaïs 李雷", settings)
    reservation = len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 64
    settings.model_request_budget = reservation + offset
    if offset < 0:
        with pytest.raises(BudgetExceededError):
            _openai_search_request("Anaïs 李雷", settings)
    else:
        assert _openai_search_request("Anaïs 李雷", settings) == body


async def test_transmitted_search_body_has_output_cap():
    requests = []
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {"sources": [{"url": "https://example.test/stats"}]},
                    }
                ]
            },
        )

    def client(**kwargs):
        return original(transport=httpx.MockTransport(handle), **kwargs)

    with (
        patch("verboisy.core.search.httpx.AsyncClient", client),
        patch("verboisy.core.search.validate_url", AsyncMock()),
    ):
        result = await openai_search("Find universities", config(max_tokens=128))
    assert result.results[0].url == "https://example.test/stats"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["max_output_tokens"] == 128
    assert body["tools"][0]["type"] == "web_search"
    assert body["tool_choice"] == "required"


async def test_initial_api_discovery_rejected_before_provider_or_browser(tmp_path):
    transport = Mock(side_effect=AssertionError("Unexpected provider transport"))
    browser = AsyncMock(side_effect=AssertionError("Unexpected browser"))
    model = AsyncMock(side_effect=AssertionError("Unexpected extraction"))
    with (
        patch("verboisy.core.search.httpx.AsyncClient", transport),
        patch("verboisy.browser.context.BrowserManager.start", browser),
        patch("verboisy.llm.client.LLMClient.complete_json", model),
        pytest.raises(BudgetExceededError),
    ):
        await arun(
            goal="Find universities",
            schema="[name,website]",
            config=config(model_request_budget=1, sqlite_db_path=str(tmp_path / "run.db")),
            max_steps=1,
        )
    transport.assert_not_called()
    browser.assert_not_awaited()
    model.assert_not_awaited()


async def test_auto_provider_does_not_bypass_budget_with_fallback():
    fallback = AsyncMock(side_effect=AssertionError("Unexpected fallback"))
    settings = config(model_request_budget=1)
    settings.search_provider = "auto"
    with patch("verboisy.core.search.brave_search", fallback), pytest.raises(BudgetExceededError):
        await web_search("Find universities", settings)
    fallback.assert_not_awaited()
