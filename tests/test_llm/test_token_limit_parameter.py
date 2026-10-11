# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit token keyword selection preserves request ceilings, retries and usage."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from verboisy.llm.client import LLMClient
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError, LLMError, LLMResponseError


def response(content='{"ok": true}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(total_tokens=11),
    )


@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("model", [None, "anthropic/explicit-test"])
async def test_exactly_one_keyword_with_same_ceiling_and_accounting(
    config, monkeypatch, parameter, model
):
    config.llm_token_limit_parameter = parameter
    config.max_tokens = 123
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    client = LLMClient(config=config)
    assert await client.complete_json("system", "user", model=model) == {"ok": True}
    kwargs = completion.await_args.kwargs
    assert kwargs[parameter] == 123
    other = "max_tokens" if parameter == "max_completion_tokens" else "max_completion_tokens"
    assert other not in kwargs
    assert kwargs["model"] == (model or config.litellm_model)
    assert kwargs["temperature"] == config.temperature
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["num_retries"] == 0
    expected = len(json.dumps(kwargs["messages"], ensure_ascii=False).encode()) + 123
    assert client.reserved_tokens == expected
    assert client.total_tokens == 11


async def test_default_remains_max_tokens(config, monkeypatch):
    monkeypatch.delenv("LLM_TOKEN_LIMIT_PARAMETER", raising=False)
    config = Settings(_env_file=None, llm_retries=0, llm_min_interval_seconds=0)
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    await LLMClient(config=config).complete_json("s", "u")
    assert completion.await_args.kwargs["max_tokens"] == config.max_tokens
    assert "max_completion_tokens" not in completion.await_args.kwargs


@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
async def test_exhausted_budget_blocks_transport_for_both_keywords(config, monkeypatch, parameter):
    config.llm_token_limit_parameter = parameter
    config.model_request_budget = 1
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    client = LLMClient(config=config)
    with pytest.raises(BudgetExceededError):
        await client.complete_json("s", "u")
    completion.assert_not_awaited()
    assert client.reserved_tokens == 0


async def test_transient_retry_reuses_selected_keyword_and_reserves_twice(config, monkeypatch):
    config.llm_token_limit_parameter = "max_completion_tokens"
    config.llm_retries = 1
    completion = AsyncMock(side_effect=[TimeoutError("transient"), response()])
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    monkeypatch.setattr("verboisy.llm.client.asyncio.sleep", AsyncMock())
    client = LLMClient(config=config)
    assert await client.complete_json("s", "u") == {"ok": True}
    for call in completion.await_args_list:
        assert call.kwargs["max_completion_tokens"] == config.max_tokens
        assert "max_tokens" not in call.kwargs
    units = len(json.dumps(completion.await_args.kwargs["messages"]).encode()) + config.max_tokens
    assert client.reserved_tokens == 2 * units
    assert client.total_tokens == 11


async def test_unsupported_parameter_does_not_trigger_keyword_fallback(config, monkeypatch):
    config.llm_token_limit_parameter = "max_completion_tokens"
    config.llm_retries = 2
    error = RuntimeError("private message")
    error.status_code = 400
    error.body = {"error": {"code": "unsupported_parameter", "param": "max_completion_tokens"}}
    completion = AsyncMock(side_effect=error)
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    with pytest.raises(LLMError, match="parameter=max_completion_tokens"):
        await LLMClient(config=config).complete_json("s", "u")
    assert completion.await_count == 1


async def test_selected_keyword_still_rejects_invalid_json(config, monkeypatch):
    config.llm_token_limit_parameter = "max_completion_tokens"
    monkeypatch.setattr("verboisy.llm.client._complete", AsyncMock(return_value=response("[]")))
    with pytest.raises(LLMResponseError):
        await LLMClient(config=config).complete_json("s", "u")


@pytest.mark.parametrize("value", ["max_output_tokens", "auto", "MAX_TOKENS", "", None])
def test_invalid_config_choices(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_token_limit_parameter=value)


def test_environment_selection(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_LIMIT_PARAMETER", "max_completion_tokens")
    assert Settings(_env_file=None).llm_token_limit_parameter == "max_completion_tokens"
