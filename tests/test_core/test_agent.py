"""Integration regressions with real model parsing and SQLite; fake browser/provider."""

import asyncio
import json
import sqlite3
from unittest.mock import Mock

import pytest
from verboisy import arun
from verboisy.core.agent import Agent
from verboisy.core.state import ActionRequest
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.exceptions import VerboisyError

from tests.conftest import action

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


async def saved(config):
    db = DatabaseManager(config.sqlite_db_path)
    try:
        return await db.load_run()
    finally:
        await db.close()


async def test_run_resume_dedup_export(config, fake_browser, model_script, tmp_path):
    output = tmp_path / "result.json"
    first_model = model_script(
        action("NAVIGATE", url="https://example.com/page2"),
        action("EXTRACT"),
        {"results": [{"name": "Alice"}]},
    )
    result = await arun(goal="Find names", schema=SCHEMA, export=output, max_steps=2, config=config)
    assert not result.completed and result.stop_reason == "max_steps"
    assert not output.exists()
    checkpoint = await saved(config)
    assert checkpoint.current_url == "https://example.com/page2"
    assert checkpoint.step_count == 2 and checkpoint.token_count == 36
    assert checkpoint.extracted_data == [{"name": "Alice"}]
    assert first_model.await_count == 3
    fake_browser.page.url = "about:blank"
    mock = model_script(
        action("EXTRACT"), {"results": [{"name": "Alice"}, {"name": "Bob"}]}, action("FINISH")
    )
    final = await arun(resume=True, goal="ignored", schema="missing.json", config=config)
    assert final.completed and final.run_id == result.run_id
    assert final.records == [{"name": "Alice"}, {"name": "Bob"}]
    assert json.loads(output.read_text()) == final.records
    prompt = json.loads(mock.await_args_list[0].kwargs["messages"][1]["content"])
    assert prompt["saved_record_count"] == 1
    assert prompt["recent_records"] == [{"name": "Alice"}]
    assert "Aurora Labs" in prompt["page_html"]
    assert prompt["goal"] == "Find names"
    fake_browser.navigate_to.assert_awaited_with("https://example.com/page2")


async def test_valid_record_survives_later_invalid_record(config, fake_browser, model_script):
    model_script(action("EXTRACT"), {"results": [{"name": "Alice"}, {"name": 17}]})
    with pytest.raises(VerboisyError):
        await arun(goal="Find names", schema=SCHEMA, config=config)
    state = await saved(config)
    assert state.status == "FAILED"
    assert state.extracted_data == [{"name": "Alice"}]
    fake_browser.close.assert_awaited()


async def test_cancellation_preserves_rows_and_releases_lock(
    config, fake_browser, model_script, monkeypatch
):
    model_script(action("EXTRACT"), {"results": [{"name": "Alice"}]}, asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await arun(goal="Find names", schema=SCHEMA, config=config)
    state = await saved(config)
    assert state.status == "INTERRUPTED" and len(state.extracted_data) == 1
    model_script(action("FINISH"))
    final = await arun(resume=state.run_id, config=config)
    assert final.completed


async def test_timeout_is_incomplete(config, fake_browser, model_script):
    async def stalled(**_kwargs):
        await asyncio.Event().wait()

    fake_browser.start.side_effect = stalled
    config.run_timeout_seconds = 0.01
    result = await arun(goal="Find names", schema=SCHEMA, config=config)
    assert not result.completed and result.stop_reason == "run_timeout"
    fake_browser.close.assert_awaited()


async def test_model_budget_is_incomplete(config, fake_browser, model_script):
    mock = model_script()
    config.max_total_tokens = 1
    result = await arun(goal="Find names", schema=SCHEMA, config=config)
    assert result.status == "PAUSED" and result.stop_reason == "model_budget"
    mock.assert_not_called()


async def test_collection_constraints_checked_at_finish(config, fake_browser, model_script):
    schema = {**SCHEMA, "minItems": 2}
    model_script(action("EXTRACT"), {"results": [{"name": "Alice"}]}, action("FINISH"))
    with pytest.raises(VerboisyError):
        await arun(goal="Two names", schema=schema, config=config)
    assert (await saved(config)).status == "FAILED"


async def test_real_dispatch_controls(config, fake_browser, model_script):
    model_script(
        action("CLICK", selector="#next"),
        action("TYPE", selector="#q", text="", submit=False),
        action("SCROLL", pixels=321),
        action("WAIT", milliseconds=0),
        action("SEARCH", query="a & b"),
        action("FINISH"),
    )
    result = await arun(goal="Find names", schema=SCHEMA, config=config)
    assert result.completed
    fake_browser.page.click.assert_awaited_once_with("#next")
    fake_browser.page.fill.assert_awaited_once_with("#q", "")
    fake_browser.page.press.assert_not_awaited()
    fake_browser.page.mouse.wheel.assert_awaited_once_with(0, 321)
    fake_browser.navigate_to.assert_awaited_once_with("https://www.google.com/search?q=a+%26+b")


async def test_database_failure_still_closes_browser(
    config, fake_browser, model_script, monkeypatch
):
    model_script(action("FINISH"))
    original = DatabaseManager.checkpoint
    calls = 0

    async def broken(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise sqlite3.OperationalError("disk full")
        await original(self, *args, **kwargs)

    monkeypatch.setattr(DatabaseManager, "checkpoint", broken)
    with pytest.raises(VerboisyError):
        await arun(goal="Find names", schema=SCHEMA, config=config)
    fake_browser.close.assert_awaited()
    db = DatabaseManager(config.sqlite_db_path)
    db.acquire_run_lock()
    await db.close()


async def test_navigation_failure_preserves_run(config, fake_browser, model_script):
    model_script(action("NAVIGATE", url="https://example.com"))
    fake_browser.navigate_to.side_effect = RuntimeError("navigation failed")
    with pytest.raises(VerboisyError):
        await arun(goal="Find names", schema=SCHEMA, config=config)
    assert (await saved(config)).status == "FAILED"


async def test_state_construction(config):
    agent = Agent("Find people", SCHEMA, 3, config=config)
    assert agent.state.status == "INITIALIZED" and agent.state.max_steps == 3


async def test_type_action_with_submit(config, fake_browser, model_script):
    """Submitting a typed value should press Enter."""
    model_script(
        action("TYPE", selector="#q", text="Alice", submit=True),
        action("FINISH"),
    )

    result = await arun(
        goal="Find names",
        schema=SCHEMA,
        config=config,
    )

    assert result.completed

    fake_browser.page.fill.assert_awaited_once_with(
        "#q",
        "Alice",
    )

    fake_browser.page.press.assert_awaited_once_with(
        "#q",
        "Enter",
    )

    fake_browser.page.wait_for_load_state.assert_awaited_once_with("domcontentloaded")


async def test_agent_lock_failure_still_cleans_up(config, fake_browser, monkeypatch):
    """Do not checkpoint when the run lock was not acquired."""
    agent = Agent(
        "Find names",
        SCHEMA,
        config=config,
    )

    acquire = Mock(side_effect=VerboisyError("lock unavailable"))

    monkeypatch.setattr(
        agent.db,
        "acquire_run_lock",
        acquire,
    )

    with pytest.raises(
        VerboisyError,
        match="lock unavailable",
    ):
        await agent.run()

    acquire.assert_called_once()

    fake_browser.close.assert_awaited()

    assert agent.db._lock is None
    assert agent.db._conn is None


async def test_final_checkpoint_failure_propagates(config, fake_browser, model_script, monkeypatch):
    """A final checkpoint failure must propagate and release resources."""
    model_script(action("FINISH"))

    agent = Agent(
        "Find names",
        SCHEMA,
        config=config,
    )

    original_checkpoint = agent.db.checkpoint
    calls = 0

    async def failing_checkpoint(*args, **kwargs):
        nonlocal calls

        calls += 1

        if calls == 3:
            raise sqlite3.OperationalError("final checkpoint failed")

        return await original_checkpoint(*args, **kwargs)

    monkeypatch.setattr(
        agent.db,
        "checkpoint",
        failing_checkpoint,
    )

    with pytest.raises(
        sqlite3.OperationalError,
        match="final checkpoint failed",
    ):
        await agent.run()

    assert calls == 3

    fake_browser.close.assert_awaited()

    assert agent.db._conn is None
    assert agent.db._lock is None


async def test_unsupported_action_is_rejected(config, fake_browser):
    """Reject an invalid internal action rather than silently ignoring it."""
    agent = Agent(
        "Find names",
        SCHEMA,
        config=config,
    )

    request = ActionRequest.model_construct(
        thought="fixture",
        action="INVALID",
        parameters={},
    )

    with pytest.raises(
        VerboisyError,
        match="Unsupported action: INVALID",
    ):
        await agent._execute(request, "")
