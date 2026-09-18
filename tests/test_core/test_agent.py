"""
Unit tests for the Core Agent loop and state machine.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from verboisy.core.agent import Agent
from verboisy.core.state import ActionRequest
from verboisy.utils.exceptions import VerboisyError


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
    _mock_db: AsyncMock,
    mock_browser: AsyncMock,
    mock_planner: AsyncMock,
    dummy_schema: dict[str, Any],
) -> None:
    # Setup mock database
    db_instance = _mock_db.return_value
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
    assert len(state.history) == 0

@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_navigate(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://start.example"
    page.content = AsyncMock(return_value="<html></html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.navigate_to = AsyncMock()
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        side_effect=[
            ActionRequest(
                thought="Navigate",
                action="NAVIGATE",
                parameters={"url": "https://example.com"},
            ),
            ActionRequest(
                thought="Done",
                action="FINISH",
                parameters={},
            ),
        ]
    )

    agent = Agent("Navigate test", dummy_schema, max_steps=5)

    with patch("verboisy.core.agent.asyncio.sleep", new_callable=AsyncMock):
        state = await agent.run()

    browser.navigate_to.assert_awaited_once_with("https://example.com")
    assert state.step_count == 2
    assert len(state.history) == 1
    assert state.history[0].action == "NAVIGATE"


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_click(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<button>Click</button>")
    page.click = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        side_effect=[
            ActionRequest(
                thought="Click button",
                action="CLICK",
                parameters={"selector": "#submit"},
            ),
            ActionRequest(
                thought="Done",
                action="FINISH",
                parameters={},
            ),
        ]
    )

    agent = Agent("Click test", dummy_schema, max_steps=5)

    with patch("verboisy.core.agent.asyncio.sleep", new_callable=AsyncMock):
        state = await agent.run()

    page.click.assert_awaited_once_with("#submit", timeout=5000)
    page.wait_for_load_state.assert_awaited_once_with("networkidle")
    assert state.history[0].action == "CLICK"


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_type(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<input>")
    page.fill = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    keyboard = Mock()
    keyboard.press = AsyncMock()
    page.keyboard = keyboard

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        side_effect=[
            ActionRequest(
                thought="Type query",
                action="TYPE",
                parameters={"selector": "#search", "text": "python"},
            ),
            ActionRequest(
                thought="Done",
                action="FINISH",
                parameters={},
            ),
        ]
    )

    agent = Agent("Type test", dummy_schema, max_steps=5)

    with patch("verboisy.core.agent.asyncio.sleep", new_callable=AsyncMock):
        state = await agent.run()

    page.fill.assert_awaited_once_with(
        "#search",
        "python",
        timeout=5000,
    )
    keyboard.press.assert_awaited_once_with("Enter")
    page.wait_for_load_state.assert_awaited_once_with("networkidle")
    assert state.history[0].action == "TYPE"


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_extract(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.save_extraction = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html>data</html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        side_effect=[
            ActionRequest(
                thought="Extract data",
                action="EXTRACT",
                parameters={},
            ),
            ActionRequest(
                thought="Done",
                action="FINISH",
                parameters={},
            ),
        ]
    )

    agent = Agent("Extract test", dummy_schema, max_steps=5)
    agent.extractor.extract_from_html = AsyncMock(
        return_value=[
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
    )

    with patch("verboisy.core.agent.asyncio.sleep", new_callable=AsyncMock):
        state = await agent.run()

    agent.extractor.extract_from_html.assert_awaited_once_with("<html>data</html>")
    assert state.extracted_data == [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]
    assert db.save_extraction.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        ("NAVIGATE", {}),
        ("CLICK", {}),
    ],
)
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_missing_required_action_parameter(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
    action: str,
    parameters: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html></html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="Invalid action",
            action=action,
            parameters=parameters,
        )
    )

    agent = Agent("Invalid parameter test", dummy_schema, max_steps=5)

    with pytest.raises(VerboisyError, match="Agent failed during execution"):
        await agent.run()

    browser.close.assert_awaited_once()
    db.close.assert_awaited_once()


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_type_missing_selector(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html></html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="Invalid type",
            action="TYPE",
            parameters={"text": "hello"},
        )
    )

    agent = Agent("Invalid type test", dummy_schema)

    with pytest.raises(VerboisyError, match="Agent failed during execution"):
        await agent.run()


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_type_missing_text(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html></html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="Invalid type",
            action="TYPE",
            parameters={"selector": "#search"},
        )
    )

    agent = Agent("Invalid type test", dummy_schema)

    with pytest.raises(VerboisyError, match="Agent failed during execution"):
        await agent.run()


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_max_steps_completes(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html></html>")

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.navigate_to = AsyncMock()
    browser.close = AsyncMock()

    planner = mock_planner.return_value
    planner.decide_next_action = AsyncMock(
        return_value=ActionRequest(
            thought="Navigate",
            action="NAVIGATE",
            parameters={"url": "https://example.org"},
        )
    )

    agent = Agent("Max steps test", dummy_schema, max_steps=1)

    with patch("verboisy.core.agent.asyncio.sleep", new_callable=AsyncMock):
        state = await agent.run()

    assert state.status == "COMPLETED"
    assert state.step_count == 1
    assert len(state.history) == 1
    browser.navigate_to.assert_awaited_once_with("https://example.org")


@pytest.mark.asyncio
@patch("verboisy.core.agent.Planner")
@patch("verboisy.core.agent.BrowserManager")
@patch("verboisy.core.agent.DatabaseManager")
async def test_agent_run_unexpected_exception_is_wrapped(
    mock_db: Mock,
    mock_browser: Mock,
    mock_planner: Mock,
    dummy_schema: dict[str, Any],
) -> None:
    db = mock_db.return_value
    db.connect = AsyncMock()
    db.save_run = AsyncMock()
    db.save_history_action = AsyncMock()
    db.close = AsyncMock()

    page = Mock()
    page.url = "https://example.com"
    page.content = AsyncMock(
        side_effect=RuntimeError("browser exploded")
    )

    browser = mock_browser.return_value
    browser.start = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    planner = mock_planner.return_value

    agent = Agent("Exception test", dummy_schema, max_steps=5)

    with pytest.raises(VerboisyError, match="browser exploded"):
        await agent.run()

    browser.close.assert_awaited_once()
    db.save_run.assert_awaited()
    db.close.assert_awaited_once()
