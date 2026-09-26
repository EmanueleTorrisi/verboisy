"""Recovery through the public API, real planner parsing and durable SQLite state."""

import asyncio
import json
import sqlite3

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from verboisy import arun
from verboisy.browser.actions import interact
from verboisy.core.state import ActionRequest
from verboisy.utils.exceptions import BrowserActionError

from tests.conftest import action
from tests.test_core.test_agent import SCHEMA, saved


async def test_timeout_replans_with_fresh_page_and_failed_selector(
    config, fake_browser, model_script
):
    fake_browser.page.content.side_effect = [
        '<button id="stale">Old filter</button>',
        '<input id="batch" type="checkbox"><label for="batch">Fall 2026</label>',
        '<select id="industry"><option value="ai">AI</option></select>',
        "<article>Alice</article>",
        "<article>Alice</article>",
    ]
    fake_browser.locator.click.side_effect = PlaywrightTimeoutError("untrusted error SECRET")
    model = model_script(
        action("CLICK", selector="#stale"),
        action("CHECK", selector="#batch", checked=True),
        action("SELECT", selector="#industry", value="ai"),
        action("EXTRACT"),
        {"results": [{"name": "Alice"}]},
        action("FINISH"),
    )
    result = await arun(goal="Read filtered directory", schema=SCHEMA, config=config)
    assert result.completed and result.records == [{"name": "Alice"}]
    prompt = json.loads(model.await_args_list[1].kwargs["messages"][1]["content"])
    failure = prompt["action_failures"][0]
    assert failure["selector"] == "#stale" and failure["error_type"] == "TimeoutError"
    assert "Fall 2026" in prompt["interactive_elements"] and "Old filter" not in prompt["page_html"]
    state = await saved(config, result.run_id)
    assert [h.action for h in state.history] == ["CHECK", "SELECT", "EXTRACT", "FINISH"]
    assert state.action_failures[0].selector == "#stale" and state.pending_action is None
    assert "SECRET" not in state.model_dump_json()
    fake_browser.locator.set_checked.assert_awaited_once_with(True, timeout=10000)
    fake_browser.locator.select_option.assert_awaited_once_with(value="ai", timeout=10000)


async def test_failure_budget_cannot_be_reset_by_successful_waits(
    config, fake_browser, model_script, tmp_path
):
    fake_browser.locator.click.side_effect = PlaywrightError("strict mode violation")
    output = tmp_path / "result.json"
    model = model_script(
        action("CLICK", selector="button"),
        action("WAIT", milliseconds=0),
        action("CLICK", selector="#missing"),
        action("WAIT", milliseconds=0),
        action("CLICK", selector="#hidden"),
        action("FINISH"),
    )
    result = await arun(goal="Read directory", schema=SCHEMA, export=output, config=config)
    assert result.status == "PAUSED" and result.stop_reason == "action_failures"
    assert model.await_count == 5 and not output.exists()
    state = await saved(config)
    assert len(state.action_failures) == 3 and state.step_count == 5
    assert [h.action for h in state.history] == ["WAIT", "WAIT"]
    assert state.token_count == 60
    fake_browser.locator.click.side_effect = None
    resumed = model_script(action("CLICK", selector="#observed"), action("FINISH"))
    final = await arun(resume=state.run_id, config=config)
    assert final.completed and output.exists()
    prompt = json.loads(resumed.await_args_list[0].kwargs["messages"][1]["content"])
    assert len(prompt["action_failures"]) == 3


async def test_failed_actions_consume_step_budget(config, fake_browser, model_script):
    fake_browser.locator.click.side_effect = PlaywrightTimeoutError("stale")
    model_script(action("CLICK", selector="#stale"))
    result = await arun(goal="Read", schema=SCHEMA, max_steps=1, config=config)
    assert result.stop_reason == "max_steps" and not result.completed
    assert len((await saved(config)).action_failures) == 1


async def test_intent_is_durable_before_dispatch_and_survives_cancellation(
    config, fake_browser, model_script
):
    async def cancelled(**_kwargs):
        with sqlite3.connect(config.sqlite_db_path) as connection:
            state = json.loads(connection.execute("SELECT state_json FROM runs").fetchone()[0])
        assert state["pending_action"]["selector"] == "#next"
        assert state["token_count"] == 12
        raise asyncio.CancelledError

    fake_browser.locator.click.side_effect = cancelled
    model_script(action("CLICK", selector="#next"))
    with pytest.raises(asyncio.CancelledError):
        await arun(goal="Read", schema=SCHEMA, config=config)
    state = await saved(config)
    assert state.status == "INTERRUPTED" and state.pending_action.selector == "#next"
    model = model_script(action("FINISH"))
    final = await arun(resume=state.run_id, config=config)
    assert final.completed
    prompt = json.loads(model.await_args.kwargs["messages"][1]["content"])
    assert prompt["interrupted_action"]["selector"] == "#next"
    assert (await saved(config, final.run_id)).pending_action is None


@pytest.mark.parametrize("operation", ["fill", "press"])
async def test_type_failure_reports_stage_without_typed_value(fake_browser, operation):
    getattr(fake_browser.locator, operation).side_effect = PlaywrightTimeoutError("SECRET RESPONSE")
    request = ActionRequest(**action("TYPE", selector="#query", text="SECRET INPUT"))
    with pytest.raises(BrowserActionError) as caught:
        await interact(fake_browser.page, request, 100)
    assert ("submit" if operation == "press" else "fill") in str(caught.value)
    assert "SECRET" not in str(caught.value)
    assert caught.value.details == {"error_type": "TimeoutError"}


async def test_search_disabled_is_enforced_and_pauses(config, fake_browser, model_script):
    config.search_provider = "disabled"
    model = model_script(action("SEARCH", query="startups"))
    result = await arun(goal="Read directory", schema=SCHEMA, config=config)
    assert result.stop_reason == "search_unavailable" and not result.completed
    fake_browser.navigate_to.assert_not_awaited()
    prompt = json.loads(model.await_args.kwargs["messages"][1]["content"])
    assert not prompt["search_enabled"]
    assert (await saved(config)).action_failures[0].message.startswith("SEARCH is disabled")


async def test_google_challenge_content_pauses_without_retry(config, fake_browser, model_script):
    fake_browser.page.content.side_effect = ["", "Unusual traffic from your computer network"]
    model = model_script(action("SEARCH", query="startups"))
    result = await arun(goal="Find startups", schema=SCHEMA, config=config)
    assert result.stop_reason == "search_unavailable" and model.await_count == 1
    state = await saved(config)
    assert state.history == [] and state.pending_action is None
    assert "automated-traffic warning" in state.action_failures[0].message
    assert state.current_url.startswith("https://www.google.com/search")
