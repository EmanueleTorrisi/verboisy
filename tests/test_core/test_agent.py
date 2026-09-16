"""
Unit tests for the Core Agent loop and state machine.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.core.agent import Agent
from verboisy.core.state import ActionRequest


@pytest.fixture
def dummy_schema() -> dict[str, Any]:
    return {"properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}


@pytest.mark.asyncio
async def test_agent_initialization(dummy_schema: dict[str, Any]) -> None:
    goal = "Find people"
    agent = Agent(goal=goal, target_schema=dummy_schema, max_steps=10)

    assert agent.state.goal == goal
    assert agent.state.max_steps == 10
    assert agent.state.status == "INITIALIZED"
    assert len(agent.state.history) == 0


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_completion(
    mock_db: AsyncMock,
    mock_browser: AsyncMock,
    mock_planner: AsyncMock,
    dummy_schema: dict[str, Any],
) -> None:
    # Setup mock database
    db_instance = mock_db.return_value
    db_instance.connect = AsyncMock()
    db_instance.save_run = AsyncMock()
    db_instance.save_history_action = AsyncMock()
    db_instance.close = AsyncMock()

    # Setup mock browser
    mock_page = AsyncMock()
    mock_page.url = "http://example.com"
    mock_page.content.return_value = "<html><body>Data</body></html>"

    browser_instance = mock_browser.return_value
    browser_instance.start = AsyncMock(return_value=mock_page)
    browser_instance.close = AsyncMock()

    # Setup mock planner to FINISH immediately
    planner_instance = mock_planner.return_value
    planner_instance.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="I am done",
            action="FINISH",
            parameters={},
        )
    )

    agent = Agent(goal="Test completion", target_schema=dummy_schema, max_steps=5)

    state = await agent.run()

    assert state.status == "COMPLETED"
    assert state.step_count == 1
    assert len(state.history) == 1
    assert state.history[0].action == "FINISH"
