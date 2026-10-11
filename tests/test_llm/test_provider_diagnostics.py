# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider diagnostics expose useful identifiers without leaking untrusted payloads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.llm.client import LLMClient
from verboisy.llm.diagnostics import provider_failure_message
from verboisy.utils.exceptions import LLMError


class ProviderFailureError(Exception):
    def __init__(self, status, *, body=None, code=None, param=None):
        super().__init__("SECRET credential, prompt and https://private.example/path")
        self.status_code = status
        self.body = body
        self.code = code
        self.param = param


@pytest.mark.parametrize(
    "status,hint",
    [
        (400, "model compatibility"),
        (401, "provider API key"),
        (403, "provider permissions"),
        (404, "model identifier"),
        (422, "provider limits"),
    ],
)
async def test_nonretryable_provider_hints_and_reserved_budget(config, monkeypatch, status, hint):
    config.llm_retries = 2
    config.llm_min_interval_seconds = 0
    error = ProviderFailureError(
        status,
        body={
            "error": {"code": "unsupported_parameter", "param": "temperature", "message": "SECRET"}
        },
    )
    completion = AsyncMock(side_effect=error)
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    client = LLMClient(config=config)
    with pytest.raises(LLMError) as raised:
        await client.complete_json("SECRET prompt", "SECRET text")
    message = str(raised.value)
    assert hint in message
    assert f"HTTP {status}" in message
    assert "code=unsupported_parameter" in message
    assert "parameter=temperature" in message
    assert "SECRET" not in message and "https://" not in message
    assert completion.await_count == 1
    assert client.reserved_tokens > 0
    assert client.total_tokens == 0


@pytest.mark.parametrize(
    "body",
    [
        None,
        "SECRET",
        [],
        {"error": "SECRET"},
        {"code": "SECRET", "param": "https://private.example"},
        {"error": {"code": [], "param": {}, "message": "SECRET"}},
    ],
)
def test_unknown_structured_fields_are_omitted(body):
    message = provider_failure_message(ProviderFailureError(400, body=body), 400)
    assert "SECRET" not in message and "https://" not in message
    assert "code=" not in message and "parameter=" not in message


def test_known_attributes_take_precedence_over_body():
    error = ProviderFailureError(
        400,
        code="context_length_exceeded",
        param="messages",
        body={"code": "invalid_api_key", "param": "model"},
    )
    message = provider_failure_message(error, 400)
    assert "context_length_exceeded" in message and "parameter=messages" in message
    assert "invalid_api_key" not in message and "parameter=model" not in message


def test_flat_body_fallback_for_unknown_attributes():
    error = ProviderFailureError(
        404, code="SECRET", param="SECRET", body={"code": "model_not_found", "param": "model"}
    )
    message = provider_failure_message(error, 404)
    assert "code=model_not_found" in message and "parameter=model" in message
    assert "SECRET" not in message


@pytest.mark.parametrize("status", [None, True, "SECRET", {"credential": "SECRET"}])
def test_untrusted_status_is_not_rendered(status):
    message = provider_failure_message(ProviderFailureError(status), status)
    assert "HTTP None" in message
    assert "SECRET" not in message


async def test_response_status_fallback_reaches_safe_diagnostics(config, monkeypatch):
    config.llm_min_interval_seconds = 0
    error = ProviderFailureError(None)
    error.response = SimpleNamespace(status_code=401)
    completion = AsyncMock(side_effect=error)
    monkeypatch.setattr("verboisy.llm.client._complete", completion)
    with pytest.raises(LLMError, match="HTTP 401.*provider API key"):
        await LLMClient(config=config).complete_json("system", "user")
    assert completion.await_count == 1
