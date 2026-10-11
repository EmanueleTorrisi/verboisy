# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Active settings inspection never executes provider code or exposes credentials."""

import json
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.llm.configuration import inspect_model_configuration


@pytest.mark.parametrize("send", [True, False])
@pytest.mark.parametrize("explicit_budget", [None, 12345])
def test_explicit_configuration_matches_effective_roles_and_request_choices(
    config, send, explicit_budget
):
    config.semantic_plan_model = "provider/semantic"
    config.source_assessment_model = "provider/assessment"
    config.extraction_model = "provider/extract"
    config.escalation_model = "provider/escalation"
    config.llm_token_limit_parameter = "max_completion_tokens"
    config.llm_send_temperature = send
    config.temperature = 0.75
    config.model_request_budget = explicit_budget
    config.litellm_api_key = SecretStr("PRIVATE_LITELLM_KEY")
    config.openai_api_key = SecretStr("PRIVATE_OPENAI_KEY")
    config.anthropic_api_key = SecretStr("PRIVATE_ANTHROPIC_KEY")
    config.litellm_api_base = "https://user:PRIVATE_PASSWORD@example.test/path?secret=PRIVATE_QUERY"
    report = inspect_model_configuration(config)
    assert report["role_models"] == {
        "semantic_plan": "provider/semantic",
        "source_assessment": "provider/assessment",
        "extraction": "provider/extract",
        "escalation": "provider/escalation",
    }
    assert report["token_limit"] == {
        "parameter": "max_completion_tokens",
        "value": config.max_tokens,
    }
    assert report["temperature"] == {"sent": send, "value": 0.75 if send else None}
    assert report["request_budget"] == {
        "configured_units": explicit_budget,
        "effective_ceiling_units": explicit_budget or config.max_total_tokens,
    }
    assert report["credentials_configured"] == {"litellm": True, "openai": True, "anthropic": True}
    assert report["custom_endpoint_configured"] is True
    encoded = json.dumps(report)
    assert "PRIVATE" not in encoded and "https://" not in encoded


def test_unset_and_empty_roles_fall_back_without_auth_claims(config):
    config.semantic_plan_model = ""
    config.openai_api_key = None
    config.anthropic_api_key = SecretStr("")
    config.litellm_api_key = None
    config.litellm_api_base = None
    report = inspect_model_configuration(config)
    assert set(report["role_models"].values()) == {config.litellm_model}
    assert report["credentials_configured"] == {
        "litellm": False,
        "openai": False,
        "anthropic": False,
    }
    assert report["custom_endpoint_configured"] is False


def test_cli_reads_active_environment_without_network_database_or_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for field in [
        "SEMANTIC_PLAN_MODEL",
        "SOURCE_ASSESSMENT_MODEL",
        "EXTRACTION_MODEL",
        "ESCALATION_MODEL",
    ]:
        monkeypatch.delenv(field, raising=False)
    monkeypatch.setenv("LITELLM_MODEL", "provider/current-model")
    monkeypatch.setenv("LLM_TOKEN_LIMIT_PARAMETER", "max_completion_tokens")
    monkeypatch.setenv("LLM_SEND_TEMPERATURE", "false")
    monkeypatch.setenv("LITELLM_API_KEY", "PRIVATE_KEY")
    monkeypatch.setenv("LITELLM_API_BASE", "https://PRIVATE_ENDPOINT")
    with (
        patch("verboisy.llm.client._complete", side_effect=AssertionError("provider call")),
        patch(
            "verboisy.browser.context.BrowserManager.start", side_effect=AssertionError("browser")
        ),
        patch("verboisy.storage.research.ResearchStore", side_effect=AssertionError("database")),
    ):
        result = CliRunner().invoke(app, ["model-config"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["default_model"] == "provider/current-model"
    assert set(report["role_models"].values()) == {"provider/current-model"}
    assert report["temperature"] == {"sent": False, "value": None}
    assert report["credentials_configured"]["litellm"] is True
    assert "PRIVATE" not in result.output
    assert not list(tmp_path.iterdir())


def test_cli_loads_dotenv_without_exposing_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_SEND_TEMPERATURE", raising=False)
    (tmp_path / ".env").write_text("LITELLM_MODEL=provider/from-file\nLLM_SEND_TEMPERATURE=false\n")
    result = CliRunner().invoke(app, ["model-config"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["default_model"] == "provider/from-file"
    assert json.loads(result.output)["temperature"]["sent"] is False
    assert {p.name for p in tmp_path.iterdir()} == {".env"}


def test_invalid_environment_reports_only_field_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_TOKEN_LIMIT_PARAMETER", "PRIVATE_BAD_VALUE")
    result = CliRunner().invoke(app, ["model-config"])
    assert result.exit_code == 1
    assert "llm_token_limit_parameter" in result.output
    assert "PRIVATE_BAD_VALUE" not in result.output
    assert not list(tmp_path.iterdir())


def test_explicit_config_does_not_reload_environment(config, monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_LIMIT_PARAMETER", "PRIVATE_INVALID")
    assert inspect_model_configuration(config)["default_model"] == config.litellm_model
