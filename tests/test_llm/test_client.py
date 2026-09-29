"""Provider boundary tests use async responses, never real credentials."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from verboisy.llm.client import LLMClient
from verboisy.utils.exceptions import BudgetExceededError, LLMError


def response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(total_tokens=7),
    )


async def test_async_response_and_credentials(config, monkeypatch):
    config.openai_api_key = SecretStr("openai-test-key")
    config.litellm_api_base = "http://localhost:4000/v1"
    mock = AsyncMock(return_value=response('{"answer":"hello"}'))
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    client = LLMClient(config=config)
    assert await client.complete_json("system", "user") == {"answer": "hello"}
    assert client.total_tokens == 7 and client.reserved_tokens > 0
    assert mock.await_args.kwargs["api_key"] == "openai-test-key"
    assert mock.await_args.kwargs["api_base"] == config.litellm_api_base
    assert mock.await_args.kwargs["num_retries"] == 0


@pytest.mark.parametrize("content", [None, "", "broken", "[]", "null", '{"value": NaN}'])
async def test_malformed_response(config, monkeypatch, content):
    monkeypatch.setattr("verboisy.llm.client._complete", AsyncMock(return_value=response(content)))
    with pytest.raises(LLMError):
        await LLMClient(config=config).complete_json("system", "user")


async def test_truncated_response(config, monkeypatch):
    value = response("{}")
    value.choices[0].finish_reason = "length"
    monkeypatch.setattr("verboisy.llm.client._complete", AsyncMock(return_value=value))
    with pytest.raises(LLMError):
        await LLMClient(config=config).complete_json("system", "user")


async def test_transient_retry(config, monkeypatch):
    config.llm_retries = 1
    error = RuntimeError("provider secret")
    error.status_code = 429
    mock = AsyncMock(side_effect=[error, response("{}")])
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    monkeypatch.setattr("verboisy.llm.client.asyncio.sleep", AsyncMock())
    assert await LLMClient(config=config).complete_json("system", "user") == {}
    assert mock.await_count == 2


async def test_nontransient_error_redacts_details(config, monkeypatch):
    config.llm_retries = 2
    mock = AsyncMock(side_effect=RuntimeError("SECRET-provider-error"))
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    with pytest.raises(LLMError) as exc:
        await LLMClient(config=config).complete_json("system", "user")
    assert "SECRET" not in str(exc.value)
    assert mock.await_count == 1


async def test_timeout_does_not_block_event_loop(config, monkeypatch):
    config.llm_timeout_seconds = 0.01
    progressed = asyncio.Event()

    async def completion(**_kwargs):
        progressed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    with pytest.raises(LLMError):
        await LLMClient(config=config).complete_json("system", "user")
    assert progressed.is_set()


async def test_cancellation_propagates(config, monkeypatch):
    monkeypatch.setattr(
        "verboisy.llm.client._complete", AsyncMock(side_effect=asyncio.CancelledError())
    )
    with pytest.raises(asyncio.CancelledError):
        await LLMClient(config=config).complete_json("system", "user")


async def test_budget_prevents_request(config, monkeypatch):
    config.max_total_tokens = 1
    mock = AsyncMock()
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    with pytest.raises(BudgetExceededError):
        await LLMClient(config=config).complete_json("system", "user")
    mock.assert_not_called()


async def test_anthropic_key_selected(config, monkeypatch):
    config.litellm_model = "anthropic/test"
    config.openai_api_key = SecretStr("wrong-key")
    config.anthropic_api_key = SecretStr("right-key")
    mock = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    await LLMClient(config=config).complete_json("system", "user")
    assert mock.await_args.kwargs["api_key"] == "right-key"


async def test_local_model_does_not_receive_cloud_key(config, monkeypatch):
    config.litellm_model = "ollama/test"
    config.openai_api_key = SecretStr("cloud-key")
    mock = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    await LLMClient(config=config).complete_json("system", "user")
    assert "api_key" not in mock.await_args.kwargs


async def test_non_integer_token_usage(config, monkeypatch):
    """Non-integer token usage should not increase the token counter."""
    value = response('{"answer":"hello"}')
    value.usage.total_tokens = None

    mock = AsyncMock(return_value=value)

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(config=config)

    result = await client.complete_json("system", "user")

    assert result == {"answer": "hello"}
    assert client.total_tokens == 0
    mock.assert_awaited_once()


async def test_shared_pacing_usage_checkpoint_and_generic_provider(config, monkeypatch):
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from verboisy.llm.client import LLMClient, _complete

    response = SimpleNamespace(
        usage=SimpleNamespace(total_tokens=7),
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")],
    )
    provider = AsyncMock(return_value=response)
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=provider))
    assert await _complete(model="custom/test") is response
    config.litellm_model = "custom/test"
    config.llm_min_interval_seconds = 10
    client = LLMClient(config=config)
    checkpoint = Mock()
    client.on_usage = checkpoint
    sleeper = AsyncMock()
    monkeypatch.setattr("verboisy.llm.client.asyncio.sleep", sleeper)
    await client.complete_json("system", "one")
    reserved = client.reserved_tokens
    await client.complete_json("system", "two")
    assert client.total_tokens == 14 and client.reserved_tokens == 2 * reserved
    assert checkpoint.call_count == 4 and sleeper.await_count == 1


async def test_explicit_gateway_key_has_priority(config, monkeypatch):
    config.litellm_api_key = SecretStr("gateway-test")
    config.openai_api_key = SecretStr("unused-test")
    mock = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", mock)
    await LLMClient(config=config).complete_json("system", "user")
    assert mock.await_args.kwargs["api_key"] == "gateway-test"


async def test_invalid_json_response_retries_then_succeeds(config, monkeypatch):
    from verboisy.utils.exceptions import LLMResponseError

    config.llm_retries = 1
    mock = AsyncMock(
        side_effect=[
            response("not json"),
            response('{"ok":true}'),
        ]
    )
    monkeypatch.setattr("verboisy.llm.client._complete", mock)

    assert await LLMClient(config=config).complete_json("system", "user") == {"ok": True}
    assert mock.await_count == 2

    mock = AsyncMock(
        side_effect=[
            response("not json"),
            response("still not json"),
        ]
    )
    monkeypatch.setattr("verboisy.llm.client._complete", mock)

    with pytest.raises(LLMResponseError):
        await LLMClient(config=config).complete_json("system", "user")

    assert mock.await_count == 2
