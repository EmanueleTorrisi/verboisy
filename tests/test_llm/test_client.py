# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider boundary tests use async responses, never real credentials."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from verboisy.llm.client import LLMClient
from verboisy.utils.exceptions import BudgetExceededError, LLMError, LLMRateLimitError


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

    mock = AsyncMock(
        side_effect=[
            error,
            response("{}"),
        ]
    )
    sleeping = AsyncMock()

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )
    monkeypatch.setattr(
        "verboisy.llm.client.asyncio.sleep",
        sleeping,
    )

    with pytest.raises(
        LLMRateLimitError,
        match="OpenAI rate limit reached",
    ):
        await LLMClient(config=config).complete_json(
            "system",
            "user",
        )

    assert mock.await_count == 1
    sleeping.assert_not_awaited()


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


def test_model_for_falls_back_to_default(config):
    client = LLMClient(
        model="default-model",
        config=config,
    )

    assert client.model_for("semantic_plan") == "default-model"


def test_model_for_uses_role_override(config):
    config.semantic_plan_model = "cheap-model"

    client = LLMClient(
        model="default-model",
        config=config,
    )

    assert client.model_for("semantic_plan") == "cheap-model"


@pytest.mark.asyncio
async def test_complete_json_uses_model_override(
    config,
    monkeypatch,
):
    mock = AsyncMock(return_value=response("{}"))

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        model="default-model",
        config=config,
    )

    assert (
        await client.complete_json(
            "system",
            "user",
            model="cheap-model",
        )
        == {}
    )

    assert mock.await_args.kwargs["model"] == "cheap-model"

    # Routing must not mutate the client's
    # default model.
    assert client.model == "default-model"


@pytest.mark.asyncio
async def test_model_override_routes_matching_credentials(
    config,
    monkeypatch,
):
    from pydantic import SecretStr

    config.litellm_api_key = None
    config.openai_api_key = SecretStr("openai-secret")
    config.anthropic_api_key = None

    mock = AsyncMock(return_value=response("{}"))

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        model="anthropic/claude-example",
        config=config,
    )

    await client.complete_json(
        "system",
        "user",
        model="gpt-example",
    )

    kwargs = mock.await_args.kwargs

    assert kwargs["model"] == "gpt-example"
    assert kwargs["api_key"] == "openai-secret"


@pytest.mark.asyncio
async def test_complete_json_for_role_routes_real_client(
    config,
    monkeypatch,
):
    from verboisy.llm.client import (
        LLMClient,
        complete_json_for_role,
    )

    config.semantic_plan_model = "cheap-model"

    mock = AsyncMock(return_value=response("{}"))

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        model="default-model",
        config=config,
    )

    result = await complete_json_for_role(
        client,
        "semantic_plan",
        "system",
        "user",
    )

    assert result == {}
    assert mock.await_args.kwargs["model"] == "cheap-model"

    # Routing never mutates the shared
    # client's default model.
    assert client.model == "default-model"


@pytest.mark.asyncio
async def test_complete_json_for_role_preserves_test_double_contract():
    from types import SimpleNamespace

    from verboisy.llm.client import (
        complete_json_for_role,
    )

    complete = AsyncMock(return_value={"ok": True})

    client = SimpleNamespace(
        complete_json=complete,
    )

    result = await complete_json_for_role(
        client,
        "extraction",
        "system",
        "user",
    )

    assert result == {"ok": True}

    complete.assert_awaited_once_with(
        "system",
        "user",
    )


@pytest.mark.asyncio
async def test_complete_json_for_role_handles_legacy_monkeypatched_client(
    config,
    monkeypatch,
):
    from verboisy.llm.client import (
        LLMClient,
        complete_json_for_role,
    )

    async def legacy_complete(
        _self,
        system_prompt,
        user_prompt,
    ):
        assert system_prompt == "system"
        assert user_prompt == "user"

        return {
            "ok": True,
        }

    monkeypatch.setattr(
        LLMClient,
        "complete_json",
        legacy_complete,
    )

    client = LLMClient(
        config=config,
    )

    result = await complete_json_for_role(
        client,
        "extraction",
        "system",
        "user",
    )

    assert result == {
        "ok": True,
    }


@pytest.mark.asyncio
async def test_complete_json_for_role_falls_back_when_signature_unavailable(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verboisy.llm.client import (
        complete_json_for_role,
    )

    complete = AsyncMock(
        return_value={"ok": True},
    )

    client = SimpleNamespace(
        complete_json=complete,
    )

    monkeypatch.setattr(
        "verboisy.llm.client.inspect.signature",
        lambda _callable: (_ for _ in ()).throw(TypeError("signature unavailable")),
    )

    result = await complete_json_for_role(
        client,
        "extraction",
        "system",
        "user",
    )

    assert result == {"ok": True}

    complete.assert_awaited_once_with(
        "system",
        "user",
    )


@pytest.mark.asyncio
async def test_validated_role_escalates_invalid_json_contract(
    config,
    monkeypatch,
):
    from verboisy.llm.client import (
        LLMClient,
        complete_validated_for_role,
    )

    config.llm_retries = 0
    config.extraction_model = "normal-model"
    config.escalation_model = "strong-model"

    mock = AsyncMock(
        side_effect=[
            response("not json"),
            response('{"value": 2}'),
        ]
    )

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        model="default-model",
        config=config,
    )

    result = await complete_validated_for_role(
        client,
        "extraction",
        "system",
        "user",
        lambda payload: payload["value"],
    )

    assert result == 2

    assert [call.kwargs["model"] for call in mock.await_args_list] == [
        "normal-model",
        "strong-model",
    ]


@pytest.mark.asyncio
async def test_validated_role_escalates_pydantic_contract_failure(
    config,
    monkeypatch,
):
    from pydantic import BaseModel, ConfigDict
    from verboisy.llm.client import (
        LLMClient,
        complete_validated_for_role,
    )

    class Contract(BaseModel):
        model_config = ConfigDict(
            extra="forbid",
            strict=True,
        )

        value: int

    config.llm_retries = 0
    config.source_assessment_model = "cheap-model"
    config.escalation_model = "strong-model"

    mock = AsyncMock(
        side_effect=[
            response('{"value":"wrong"}'),
            response('{"value":2}'),
        ]
    )

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        model="default-model",
        config=config,
    )

    result = await complete_validated_for_role(
        client,
        "source_assessment",
        "system",
        "user",
        Contract.model_validate,
    )

    assert result.value == 2

    assert [call.kwargs["model"] for call in mock.await_args_list] == [
        "cheap-model",
        "strong-model",
    ]


@pytest.mark.asyncio
async def test_validated_role_does_not_escalate_without_configured_model(
    config,
    monkeypatch,
):
    from verboisy.llm.client import (
        LLMClient,
        complete_validated_for_role,
    )
    from verboisy.utils.exceptions import (
        LLMResponseError,
    )

    config.llm_retries = 0
    config.escalation_model = None

    mock = AsyncMock(return_value=response("not json"))

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        config=config,
    )

    with pytest.raises(LLMResponseError):
        await complete_validated_for_role(
            client,
            "extraction",
            "system",
            "user",
            dict,
        )

    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_validated_role_does_not_escalate_rate_limit(
    config,
    monkeypatch,
):
    from verboisy.llm.client import (
        LLMClient,
        complete_validated_for_role,
    )
    from verboisy.utils.exceptions import (
        LLMRateLimitError,
    )

    config.llm_retries = 0
    config.extraction_model = "normal-model"
    config.escalation_model = "strong-model"

    error = RuntimeError("rate limited")
    error.status_code = 429

    mock = AsyncMock(side_effect=error)

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        config=config,
    )

    with pytest.raises(LLMRateLimitError):
        await complete_validated_for_role(
            client,
            "extraction",
            "system",
            "user",
            dict,
        )

    assert mock.await_count == 1


def test_escalation_unavailable_without_model_for():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verboisy.llm.client import (
        escalation_available,
    )

    client = SimpleNamespace(
        config=SimpleNamespace(
            escalation_model="strong-model",
        ),
        complete_json=AsyncMock(),
    )

    assert not escalation_available(
        client,
        "extraction",
    )


def test_escalation_unavailable_without_complete_json():
    from types import SimpleNamespace

    from verboisy.llm.client import (
        escalation_available,
    )

    class Client:
        config = SimpleNamespace(
            escalation_model="strong-model",
        )
        complete_json = None

        def model_for(self, role):
            if role == "escalation":
                return "strong-model"
            return "normal-model"

    assert not escalation_available(
        Client(),
        "extraction",
    )


def test_escalation_unavailable_when_signature_cannot_be_inspected(
    monkeypatch,
):
    from types import SimpleNamespace

    from verboisy.llm.client import (
        escalation_available,
    )

    class Client:
        config = SimpleNamespace(
            escalation_model="strong-model",
        )

        async def complete_json(
            self,
            _system_prompt,
            _user_prompt,
            *,
            _model=None,
        ):
            return {}

        def model_for(self, role):
            if role == "escalation":
                return "strong-model"
            return "normal-model"

    def fail_signature(_callable):
        raise TypeError("signature unavailable")

    monkeypatch.setattr(
        "verboisy.llm.client.inspect.signature",
        fail_signature,
    )

    assert not escalation_available(
        Client(),
        "extraction",
    )


def test_escalation_unavailable_for_legacy_complete_json_signature():
    from types import SimpleNamespace

    from verboisy.llm.client import (
        escalation_available,
    )

    class Client:
        config = SimpleNamespace(
            escalation_model="strong-model",
        )

        async def complete_json(
            self,
            _system_prompt,
            _user_prompt,
        ):
            return {}

        def model_for(self, role):
            if role == "escalation":
                return "strong-model"
            return "normal-model"

    assert not escalation_available(
        Client(),
        "extraction",
    )


@pytest.mark.asyncio
async def test_validated_role_reports_escalation(
    config,
    monkeypatch,
):
    from unittest.mock import MagicMock

    from verboisy.llm.client import (
        LLMClient,
        complete_validated_for_role,
    )

    config.llm_retries = 0
    config.extraction_model = "cheap-model"
    config.escalation_model = "strong-model"

    mock = AsyncMock(
        side_effect=[
            response("not json"),
            response('{"value":2}'),
        ]
    )

    monkeypatch.setattr(
        "verboisy.llm.client._complete",
        mock,
    )

    client = LLMClient(
        config=config,
    )

    on_escalation = MagicMock()
    client.on_escalation = on_escalation

    result = await complete_validated_for_role(
        client,
        "extraction",
        "system",
        "user",
        lambda payload: payload["value"],
    )

    assert result == 2

    on_escalation.assert_called_once_with(
        {
            "role": "extraction",
            "reason": "invalid_model_response",
            "primary_model": "cheap-model",
            "escalation_model": "strong-model",
        }
    )
