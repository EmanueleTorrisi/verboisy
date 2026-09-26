"""Tests for unavailable search-provider responses."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.agent import Agent
from verboisy.core.state import ActionRequest
from verboisy.utils.exceptions import VerboisyError


def make_search_agent(monkeypatch, final_url):
    """Create an agent with a mocked browser."""

    agent = object.__new__(Agent)
    agent.config = MagicMock()
    agent.config.search_provider = "google"

    page = MagicMock()
    page.url = final_url
    page.content = AsyncMock(return_value="<html>Results</html>")

    agent.browser = MagicMock()

    agent.browser.get_page = AsyncMock(return_value=page)

    agent.browser.navigate_to = AsyncMock()

    agent.state = MagicMock()

    monkeypatch.setattr(
        "verboisy.core.agent.validate_url",
        AsyncMock(),
    )

    return agent


@pytest.mark.asyncio
async def test_google_warning_stops_search(
    monkeypatch,
):
    agent = make_search_agent(
        monkeypatch,
        "https://www.google.com/sorry/index" "?continue=example",
    )

    request = ActionRequest(
        thought="Search for startups",
        action="SEARCH",
        parameters={
            "query": "YC F26 AI startups",
        },
    )

    with pytest.raises(
        VerboisyError,
        match="Search provider unavailable",
    ) as exc_info:
        await agent._execute(
            request,
            "<html>Unusual traffic</html>",
        )

    assert "No search results were obtained" in str(exc_info.value)

    agent.browser.navigate_to.assert_awaited_once_with(
        "https://www.google.com/search?q=" "YC+F26+AI+startups"
    )


@pytest.mark.parametrize(
    "final_url",
    [
        "https://www.google.com/search?q=startups",
        "https://www.example.com/results",
    ],
)
@pytest.mark.asyncio
async def test_normal_search_navigation_is_allowed(
    monkeypatch,
    final_url,
):
    agent = make_search_agent(
        monkeypatch,
        final_url,
    )

    request = ActionRequest(
        thought="Search for companies",
        action="SEARCH",
        parameters={
            "query": "startup companies",
        },
    )

    await agent._execute(
        request,
        "<html>Results</html>",
    )

    agent.browser.navigate_to.assert_awaited_once()

    assert agent.state.current_url == final_url
