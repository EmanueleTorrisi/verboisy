from unittest.mock import AsyncMock

import pytest
from verboisy.core.planner import Planner
from verboisy.core.state import ActionHistory
from verboisy.utils.exceptions import PlanningError


@pytest.mark.asyncio
async def test_planner_returns_valid_action() -> None:
    planner = Planner()

    planner.llm.complete_json = AsyncMock(
        return_value={
            "thought": "Click the button",
            "action": "CLICK",
            "parameters": {"selector": "#submit"},
        }
    )

    result = await planner.decide_next_action(
        goal="Submit the form",
        current_url="https://example.com",
        html_content="<button id='submit'>Submit</button>",
        history=[],
    )

    assert result.action == "CLICK"
    assert result.parameters == {"selector": "#submit"}
    planner.llm.complete_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_planner_handles_history() -> None:
    planner = Planner()

    planner.llm.complete_json = AsyncMock(
        return_value={
            "thought": "Finish",
            "action": "FINISH",
            "parameters": {},
        }
    )

    history = [
        ActionHistory(
            action="NAVIGATE",
            parameters={"url": "https://example.com"},
            url="https://start.example",
        )
    ]

    result = await planner.decide_next_action(
        goal="Finish task",
        current_url="https://example.com",
        html_content="<html></html>",
        history=history,
    )

    assert result.action == "FINISH"

    prompt = planner.llm.complete_json.await_args.args[1]
    assert "NAVIGATE" in prompt
    assert "https://start.example" in prompt


@pytest.mark.asyncio
async def test_planner_wraps_llm_errors() -> None:
    planner = Planner()

    planner.llm.complete_json = AsyncMock(
        side_effect=RuntimeError("LLM unavailable")
    )

    with pytest.raises(
        PlanningError,
        match="Planner failed to generate valid action request",
    ):
        await planner.decide_next_action(
            goal="Find data",
            current_url="https://example.com",
            html_content="<html></html>",
            history=[],
        )
