# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Offline fixtures. Only explicitly marked live tests call a real model."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
        search_provider="disabled",
        browser_action_timeout_ms=10000,
        max_action_failures=3,
        llm_min_interval_seconds=0,
    )


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
