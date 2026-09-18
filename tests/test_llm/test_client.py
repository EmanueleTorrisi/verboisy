from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import verboisy.llm.client as client_module
from verboisy.llm.client import LLMClient
from verboisy.utils.exceptions import LLMError


def make_response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


@pytest.mark.asyncio
async def test_complete_json_returns_parsed_response(monkeypatch) -> None:
    completion = Mock(return_value=make_response('{"answer": "hello"}'))
    monkeypatch.setattr(client_module, "completion", completion)

    client = LLMClient(model="test-model")

    result = await client.complete_json("system", "user")

    assert result == {"answer": "hello"}

    completion.assert_called_once_with(
        model="test-model",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        temperature=client_module.settings.temperature,
        max_tokens=client_module.settings.max_tokens,
        response_format={"type": "json_object"},
    )


@pytest.mark.asyncio
async def test_complete_json_raises_on_empty_content(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module,
        "completion",
        Mock(return_value=make_response(None)),
    )

    client = LLMClient(model="test-model")

    with pytest.raises(LLMError, match="LLM request failed"):
        await client.complete_json("system", "user")


@pytest.mark.asyncio
async def test_complete_json_raises_on_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module,
        "completion",
        Mock(return_value=make_response("not valid json")),
    )

    client = LLMClient(model="test-model")

    with pytest.raises(LLMError, match="LLM request failed"):
        await client.complete_json("system", "user")


@pytest.mark.asyncio
async def test_complete_json_raises_on_completion_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module,
        "completion",
        Mock(side_effect=RuntimeError("provider failed")),
    )

    client = LLMClient(model="test-model")

    with pytest.raises(LLMError, match="LLM request failed"):
        await client.complete_json("system", "user")


def test_llm_client_uses_default_model(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module.settings,
        "litellm_model",
        "configured-model",
    )

    client = LLMClient()

    assert client.model == "configured-model"
