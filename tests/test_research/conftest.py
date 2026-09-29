import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_research.test_contracts import PAGES


@pytest.fixture
def world(monkeypatch):
    page = SimpleNamespace(
        url="about:blank", content=AsyncMock(), evaluate=AsyncMock(), locator=Mock()
    )

    async def navigate(url):
        page.url = url
        page.content.return_value = PAGES[url]
        page.evaluate.return_value = {
            "url": url,
            "html": PAGES[url],
            "visible_html": PAGES[url],
            "oversized": False,
        }

    browser = SimpleNamespace(
        start=AsyncMock(return_value=page),
        get_page=AsyncMock(return_value=page),
        navigate_to=AsyncMock(side_effect=navigate),
        close=AsyncMock(),
    )
    monkeypatch.setattr("verboisy.core.research.BrowserManager", lambda **_kwargs: browser)

    async def respond(self, system, prompt):
        payload = json.loads(prompt)
        if "candidate" in payload:
            return {
                "relevant": True,
                "same_entity": True,
                "supported_fields": list(payload["candidate"]["evidence"]),
                "rejected_fields": [],
            }
        sources = {s["text"]: s for s in payload["sources"]}
        if not any(s in sources for s in ("31", "22")):
            return {"candidates": [], "priority_links": []}
        name, age = ("Alice", 31) if "31" in sources else ("Bob", 22)
        c = {
            "scope": sources[name]["scope"],
            "record": {"customer": name, "age": age},
            "evidence": {
                "/customer": {"source": sources[name]["id"], "quote": name},
                "/age": {
                    "source": sources[str(age)]["id"],
                    "quote": str(age),
                    "transform": "integer",
                },
            },
        }
        return {"candidates": [c], "priority_links": []}

    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", respond)
    return browser
