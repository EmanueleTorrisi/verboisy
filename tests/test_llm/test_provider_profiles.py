# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Heterogeneous providers share accounting while keeping request contracts isolated."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError
from verboisy.llm.client import LLMClient, complete_json_for_role, complete_validated_for_role
from verboisy.llm.configuration import inspect_model_configuration
from verboisy.llm.providers import ProviderProfile, resolve_provider
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError, LLMResponseError

from tests.test_llm.test_client import response


@pytest.mark.parametrize("mode", ["json_object", "prompt"])
@pytest.mark.parametrize("parameter", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("temperature", [False, True])
async def test_profile_controls_transport_and_reservation(
    config, monkeypatch, mode, parameter, temperature
):
    config.llm_provider_profiles = {
        "custom/": ProviderProfile(
            api_key=SecretStr("PROFILE_KEY"),
            api_base="http://localhost:8123/v1",
            response_mode=mode,
            token_limit_parameter=parameter,
            max_tokens=123,
            send_temperature=temperature,
        )
    }
    transport = AsyncMock(return_value=response('{"answer":42}'))
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    client = LLMClient(config=config)
    assert await client.complete_json("system", "user", model="custom/test") == {"answer": 42}
    sent = transport.await_args.kwargs
    assert sent[parameter] == 123
    assert ("response_format" in sent) == (mode == "json_object")
    assert ("temperature" in sent) == temperature
    assert sent["api_key"] == "PROFILE_KEY"
    assert sent["api_base"] == "http://localhost:8123/v1"
    assert sent["num_retries"] == 0
    assert "Return a single valid JSON object" in sent["messages"][0]["content"]
    assert (
        client.reserved_tokens
        == len(json.dumps(sent["messages"], ensure_ascii=False).encode()) + 123
    )
    assert client.total_tokens == 7


@pytest.mark.parametrize("role", ["semantic_plan", "source_assessment", "extraction", "escalation"])
async def test_roles_use_their_own_endpoint_and_key(config, monkeypatch, role):
    setattr(config, f"{role}_model", "other/test")
    config.litellm_api_key = SecretStr("GLOBAL_KEY")
    config.litellm_api_base = "https://global.test/v1"
    config.llm_provider_profiles = {
        "other/": ProviderProfile(api_key=SecretStr("OTHER_KEY"), api_base="https://other.test/v1")
    }
    transport = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    await complete_json_for_role(LLMClient(config=config), role, "system", "user")
    assert transport.await_args.kwargs["model"] == "other/test"
    assert transport.await_args.kwargs["api_key"] == "OTHER_KEY"
    assert transport.await_args.kwargs["api_base"] == "https://other.test/v1"


async def test_explicit_local_profile_does_not_inherit_cloud_routing(config, monkeypatch):
    config.litellm_api_key = SecretStr("GLOBAL_KEY")
    config.openai_api_key = SecretStr("OPENAI_KEY")
    config.litellm_api_base = "https://global.test/v1"
    config.llm_provider_profiles = {"openai/local": ProviderProfile(response_mode="prompt")}
    transport = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    await LLMClient(config=config).complete_json("system", "user", model="openai/local")
    assert "api_key" not in transport.await_args.kwargs
    assert "api_base" not in transport.await_args.kwargs


def test_longest_prefix_wins_independently_of_insertion_order(config):
    specific = ProviderProfile(max_tokens=111, send_temperature=False)
    general = ProviderProfile(max_tokens=222)
    for profiles in (
        {"openai/": general, "openai/local": specific},
        {"openai/local": specific, "openai/": general},
    ):
        config.llm_provider_profiles = profiles
        resolved = resolve_provider(config, "openai/local-model")
        assert resolved.prefix == "openai/local"
        assert resolved.max_tokens == 111
        assert resolved.send_temperature is False
        assert resolve_provider(config, "openai/cloud").max_tokens == 222


def test_profile_inherits_capability_defaults_but_not_gateway_credentials(config):
    config.llm_token_limit_parameter = "max_completion_tokens"
    config.llm_send_temperature = False
    config.llm_provider_profiles = {"provider/": ProviderProfile()}
    resolved = resolve_provider(config, "provider/test")
    assert resolved.max_tokens == config.max_tokens
    assert resolved.token_limit_parameter == "max_completion_tokens"
    assert resolved.send_temperature is False


async def test_global_prompt_mode_preserves_legacy_credentials(config, monkeypatch):
    config.llm_response_mode = "prompt"
    config.openai_api_key = SecretStr("LEGACY_KEY")
    transport = AsyncMock(return_value=response("{}"))
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    await LLMClient(config=config).complete_json("system", "user")
    assert "response_format" not in transport.await_args.kwargs
    assert transport.await_args.kwargs["api_key"] == "LEGACY_KEY"


@pytest.mark.parametrize("content", ["not JSON", "[]", '{"value":NaN}', "```json\n{}\n```"])
async def test_prompt_mode_keeps_strict_json_validation(config, monkeypatch, content):
    config.llm_response_mode = "prompt"
    config.llm_retries = 0
    monkeypatch.setattr("verboisy.llm.client._complete", AsyncMock(return_value=response(content)))
    with pytest.raises(LLMResponseError):
        await LLMClient(config=config).complete_json("system", "user")


async def test_profile_budget_blocks_before_transport(config, monkeypatch):
    config.model_request_budget = 1
    config.llm_provider_profiles = {"provider/": ProviderProfile(max_tokens=2000)}
    transport = AsyncMock()
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    client = LLMClient(config=config)
    with pytest.raises(BudgetExceededError):
        await client.complete_json("system", "user", model="provider/test")
    transport.assert_not_awaited()
    assert client.reserved_tokens == 0


async def test_escalation_switches_profiles_and_preserves_shared_budget(config, monkeypatch):
    config.extraction_model = "first/model"
    config.escalation_model = "second/model"
    config.llm_retries = 0
    config.llm_provider_profiles = {
        "first/": ProviderProfile(max_tokens=100, response_mode="prompt"),
        "second/": ProviderProfile(max_tokens=200, api_key=SecretStr("SECOND_KEY")),
    }
    transport = AsyncMock(side_effect=[response("invalid"), response('{"value":1}')])
    monkeypatch.setattr("verboisy.llm.client._complete", transport)
    client = LLMClient(config=config)
    observed = []
    client.on_usage = lambda: observed.append((client.reserved_tokens, client.total_tokens))
    assert await complete_validated_for_role(client, "extraction", "s", "u", lambda x: x) == {
        "value": 1
    }
    first, second = (call.kwargs for call in transport.await_args_list)
    assert "api_key" not in first and "response_format" not in first
    assert second["api_key"] == "SECOND_KEY"
    expected = (
        sum(
            len(json.dumps(call["messages"], ensure_ascii=False).encode())
            for call in (first, second)
        )
        + 300
    )
    assert client.reserved_tokens == expected and client.total_tokens == 14
    assert observed[-1] == (expected, 14)


def test_inspection_reports_effective_roles_without_endpoint_or_key_values(config):
    config.extraction_model = "private/model"
    config.llm_provider_profiles = {
        "private/": ProviderProfile(
            api_key=SecretStr("PRIVATE_KEY"),
            api_base="https://user:PRIVATE_PASSWORD@private.test/v1?secret=PRIVATE_QUERY",
            response_mode="prompt",
            max_tokens=777,
            send_temperature=False,
        )
    }
    report = inspect_model_configuration(config)
    assert report["provider_profile_count"] == 1
    effective = report["effective_provider_settings"]["extraction"]
    assert effective["token_limit"]["value"] == 777
    assert effective["response_mode"] == "prompt"
    assert effective["credentials_configured"] and effective["custom_endpoint_configured"]
    assert "PRIVATE" not in json.dumps(report) and "https://" not in json.dumps(report)


def test_profiles_load_from_environment_without_secret_error_output(monkeypatch):
    monkeypatch.setenv(
        "LLM_PROVIDER_PROFILES",
        json.dumps({"provider/": {"max_tokens": 321, "response_mode": "prompt"}}),
    )
    config = Settings(_env_file=None)
    assert resolve_provider(config, "provider/model").max_tokens == 321
    monkeypatch.setenv(
        "LLM_PROVIDER_PROFILES",
        json.dumps({"provider/": {"api_key": "PRIVATE_KEY", "max_tokens": 0}}),
    )
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    assert "PRIVATE_KEY" not in str(error.value)


@pytest.mark.parametrize("prefix", ["", " ", "provider with spaces", "provider\n", "x" * 257])
def test_invalid_prefixes_fail_at_settings_load(prefix):
    with pytest.raises(ValidationError, match="Provider prefixes"):
        Settings(_env_file=None, llm_provider_profiles={prefix: {}})


@pytest.mark.parametrize(
    "profile",
    [
        {"max_tokens": 0},
        {"max_tokens": True},
        {"max_tokens": 1.5},
        {"send_temperature": "false"},
        {"response_mode": "auto"},
        {"token_limit_parameter": "guess"},
        {"api_base": ""},
        {"unknown": True},
    ],
)
def test_invalid_capabilities_fail_before_provider_transport(profile):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider_profiles={"provider/": profile})
