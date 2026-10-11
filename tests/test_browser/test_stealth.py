# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.browser.stealth import StealthManager


def test_get_random_user_agent_returns_known_value(monkeypatch) -> None:
    monkeypatch.setattr(
        "verboisy.browser.stealth.random.choice",
        lambda values: values[0],
    )

    result = StealthManager.get_random_user_agent()

    assert result == StealthManager.USER_AGENTS[0]


@pytest.mark.asyncio
async def test_apply_stealth_adds_both_init_scripts() -> None:
    page = Mock()
    page.add_init_script = AsyncMock()

    await StealthManager.apply_stealth(page)

    assert page.add_init_script.await_count == 2

    first_script = page.add_init_script.await_args_list[0].args[0]
    second_script = page.add_init_script.await_args_list[1].args[0]

    assert "navigator" in first_script
    assert "webdriver" in first_script

    assert "plugins" in second_script
    assert "languages" in second_script
