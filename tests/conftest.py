"""Offline fixtures. Only explicitly marked live tests call a real model."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_html_fixture(name: str) -> str:
    return (FIXTURES_DIR / "pages" / name).read_text(encoding="utf-8")


def load_json_fixture(name: str) -> list | dict:
    return json.loads((FIXTURES_DIR / "expected" / name).read_text(encoding="utf-8"))


@pytest.fixture
def config(tmp_path):
    return Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "runs.db"),
        action_delay_seconds=0,
        allow_private_network=True,
        browser_sandbox=False,
        llm_retries=0,
        litellm_model="openai/test",
        user_agent_rotation=False,
        search_provider="google",
        browser_action_timeout_ms=10000,
        max_action_failures=3,
    )


@pytest.fixture
async def test_db(config) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(config.sqlite_db_path)
    await manager.connect()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
def fake_browser(monkeypatch):
    locator = SimpleNamespace(
        click=AsyncMock(),
        fill=AsyncMock(),
        press=AsyncMock(),
        set_checked=AsyncMock(),
        select_option=AsyncMock(),
    )
    page = SimpleNamespace(
        url="about:blank",
        content=AsyncMock(return_value=load_html_fixture("startup_directory.html")),
        click=AsyncMock(),
        fill=AsyncMock(),
        press=AsyncMock(),
        wait_for_load_state=AsyncMock(),
        mouse=SimpleNamespace(wheel=AsyncMock()),
        locator=Mock(return_value=locator),
    )

    async def navigate(url):
        page.url = url

    browser = SimpleNamespace(
        start=AsyncMock(return_value=page),
        get_page=AsyncMock(return_value=page),
        navigate_to=AsyncMock(side_effect=navigate),
        close=AsyncMock(),
        page=page,
        locator=locator,
    )
    monkeypatch.setattr("verboisy.core.agent.BrowserManager", lambda **_kwargs: browser)
    return browser


@pytest.fixture
def model_script(monkeypatch):
    def configure(*responses):
        def convert(payload):
            if isinstance(payload, BaseException):
                return payload
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop"
                    )
                ],
                usage=SimpleNamespace(total_tokens=12),
            )

        mock = AsyncMock(side_effect=[convert(r) for r in responses])
        monkeypatch.setattr("verboisy.llm.client._complete", mock)
        return mock

    return configure


def action(name, **parameters):
    return {"thought": "test fixture decision", "action": name, "parameters": parameters}
