"""Keep the client's sanitized failures visible through wrappers and the CLI."""

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.core.planner import Planner
from verboisy.extractor.engine import ExtractionEngine
from verboisy.utils.exceptions import ExtractionError, PlanningError


@pytest.mark.parametrize("component", ["planner", "extractor"])
@pytest.mark.parametrize(
    "status,provider_message,expected",
    [
        (429, "SECRET-api-key temporary limit", "HTTP 429"),
        (429, "SECRET-api-key insufficient_quota", "quota or daily limit"),
        (401, "SECRET-api-key authentication failure", "HTTP 401"),
    ],
)
async def test_model_diagnostic_survives_wrapping(
    config, monkeypatch, component, status, provider_message, expected
):
    error = RuntimeError(provider_message)
    error.status_code = status
    completion = AsyncMock(side_effect=error)
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    if component == "planner":
        operation = Planner(config=config).decide_next_action(
            "SECRET-goal", "https://example.com", "<p>SECRET-page</p>", []
        )
        expected_exception = PlanningError
    else:
        operation = ExtractionEngine(
            {"type": "object", "properties": {"name": {"type": "string"}}},
            config=config,
        ).extract_from_html("<p>SECRET-page</p>", "SECRET-goal")
        expected_exception = ExtractionError
    with pytest.raises(expected_exception) as caught:
        await operation
    assert "model call failed" in str(caught.value)
    assert expected in str(caught.value)
    assert "SECRET" not in str(caught.value)
    completion.assert_awaited_once()


def test_model_http_status_reaches_cli_with_saved_run(
    config, fake_browser, model_script, monkeypatch, tmp_path
):
    error = RuntimeError("SECRET-provider-message")
    error.status_code = 429
    completion = model_script(error)
    monkeypatch.setattr("verboisy.cli.main.Settings", lambda: config)
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"name": {"type": "string"}}}))
    output = tmp_path / "result.json"
    invocation = CliRunner().invoke(
        app,
        ["run", "--goal", "Find names", "--schema", str(schema), "--export", str(output)],
    )
    assert invocation.exit_code == 1
    message = " ".join(invocation.output.split())
    assert "Planner model call failed" in message
    assert "HTTP 429" in message
    assert "SECRET" not in invocation.output
    assert not output.exists()
    completion.assert_awaited_once()
    with sqlite3.connect(config.sqlite_db_path) as db:
        state = json.loads(db.execute("SELECT state_json FROM runs").fetchone()[0])
    assert state["status"] == "FAILED"
    assert state["stop_reason"] == "PlanningError"
    assert state["run_id"] in invocation.output
