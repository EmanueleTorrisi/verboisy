# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Caller-controlled temperature omission leaves JSON, retries and accounting intact."""

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
        usage=SimpleNamespace(total_tokens=7),
    )


@pytest.mark.parametrize("send", [True, False])
@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
async def test_caller_choice_combines_with_token_keyword(config, monkeypatch, send, parameter):
    config.llm_send_temperature = send
    config.temperature = 0.75
    config.llm_token_limit_parameter = parameter
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    client = LLMClient(config=config)
    assert await client.complete_json("s", "u", model="provider/override") == {"ok": True}
    kwargs = completion.await_args.kwargs
    if send:
        assert kwargs["temperature"] == 0.75
    else:
        assert "temperature" not in kwargs
    assert kwargs["model"] == "provider/override"
    assert kwargs[parameter] == config.max_tokens
    assert kwargs["response_format"] == {"type": "json_object"}
    units = len(json.dumps(kwargs["messages"]).encode()) + config.max_tokens
    assert client.reserved_tokens == units
    assert client.total_tokens == 7


async def test_default_still_sends_validated_temperature(monkeypatch):
    monkeypatch.delenv("LLM_SEND_TEMPERATURE", raising=False)
    config = Settings(_env_file=None, temperature=1, llm_retries=0, llm_min_interval_seconds=0)
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    await LLMClient(config=config).complete_json("s", "u")
    assert completion.await_args.kwargs["temperature"] == 1


async def test_retry_preserves_omission_and_reserves_each_attempt(config, monkeypatch):
    config.llm_send_temperature = False
    config.llm_retries = 1
    completion = AsyncMock(side_effect=[TimeoutError(), response()])
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    monkeypatch.setattr("verboisy.llm.client.asyncio.sleep", AsyncMock())
    client = LLMClient(config=config)
    assert await client.complete_json("s", "u") == {"ok": True}
    assert all("temperature" not in call.kwargs for call in completion.await_args_list)
    units = len(json.dumps(completion.await_args.kwargs["messages"]).encode()) + config.max_tokens
    assert client.reserved_tokens == 2 * units


async def test_unsupported_temperature_does_not_auto_drop_parameter(config, monkeypatch):
    config.llm_send_temperature = True
    config.llm_retries = 2
    error = RuntimeError("private response")
    error.status_code = 400
    error.body = {"code": "unsupported_parameter", "param": "temperature"}
    completion = AsyncMock(side_effect=error)
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    with pytest.raises(LLMError, match="parameter=temperature"):
        await LLMClient(config=config).complete_json("s", "u")
    assert completion.await_count == 1
    assert completion.await_args.kwargs["temperature"] == config.temperature


async def test_omission_does_not_bypass_request_budget(config, monkeypatch):
    config.llm_send_temperature = False
    config.model_request_budget = 1
    completion = AsyncMock(return_value=response())
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    with pytest.raises(BudgetExceededError):
        await LLMClient(config=config).complete_json("s", "u")
    completion.assert_not_awaited()


async def test_omission_keeps_json_validation(config, monkeypatch):
    config.llm_send_temperature = False
    monkeypatch.setattr("verboisy.llm.client._complete", AsyncMock(return_value=response("[]")))
    with pytest.raises(LLMResponseError):
        await LLMClient(config=config).complete_json("s", "u")


@pytest.mark.parametrize("value", ["auto", "", None])
def test_invalid_omission_setting_is_rejected(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_send_temperature=value)


@pytest.mark.parametrize("temperature", [-1, 3])
def test_temperature_stays_validated_when_omitted(temperature):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_send_temperature=False, temperature=temperature)


def test_environment_false_omits_and_explicit_value_wins(monkeypatch):
    monkeypatch.setenv("LLM_SEND_TEMPERATURE", "false")
    assert Settings(_env_file=None).llm_send_temperature is False
    assert Settings(_env_file=None, llm_send_temperature=True).llm_send_temperature is True
