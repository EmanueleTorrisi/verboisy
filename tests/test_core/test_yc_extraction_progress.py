"""Offline tests for extraction progress recorded in action history."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.agent import Agent
from verboisy.core.state import ActionRequest
from verboisy.utils.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate_count", "save_success", "expected_saved"),
    [
        (0, True, 0),
        (1, True, 1),
        (1, False, 0),
    ],
)
async def test_extraction_progress_recorded(
    candidate_count: int,
    save_success: bool,
    expected_saved: int,
) -> None:
    """Use mocks; do not contact a browser, database or model provider."""

    db = SimpleNamespace(
        acquire_run_lock=MagicMock(),
        connect=AsyncMock(),
        checkpoint=AsyncMock(),
        save_extraction=AsyncMock(return_value=save_success),
        close=AsyncMock(),
        _lock=object(),
        _conn=object(),
    )

    config = settings.model_copy(update={"action_delay_seconds": 0})

    schema = {
        "type": "array",
        "items": {"type": "object"},
    }

    agent = Agent(
        "Fixture goal",
        schema,
        max_steps=1,
        config=config,
        db=db,
    )

    page = SimpleNamespace(
        url="about:blank",
        content=AsyncMock(return_value="<html><body>Fixture</body></html>"),
    )

    agent.browser.start = AsyncMock(return_value=page)
    agent.browser.get_page = AsyncMock(return_value=page)
    agent.browser.close = AsyncMock()

    agent.planner.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="Fixture",
            action="EXTRACT",
        )
    )

    async def fake_candidates(html: str, goal: str):
        for _ in range(candidate_count):
            yield {
                "name": "Fixture",
                "website": "https://example.com",
            }

    agent.extractor.iter_from_html = fake_candidates

    state = await agent.run()

    assert len(state.history) == 1
    assert state.history[0].action == "EXTRACT"

    assert state.history[0].parameters == {"saved_records": expected_saved}

    assert len(state.extracted_data) == expected_saved
    assert db.save_extraction.await_count == candidate_count
