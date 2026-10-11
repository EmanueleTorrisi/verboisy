# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Active model settings inspection without requests, persistence or credential values."""

from typing import Any

from verboisy.llm.client import LLMClient, ModelRole
from verboisy.llm.providers import resolve_provider
from verboisy.utils.config import Settings


def inspect_model_configuration(config: Settings | None = None) -> dict[str, Any]:
    """Return only explicit safe summary fields; never serialize the Settings object."""
    active = config if config is not None else Settings()
    client = LLMClient(config=active)
    roles: tuple[ModelRole, ...] = (
        "semantic_plan",
        "source_assessment",
        "extraction",
        "escalation",
    )
    return {
        "configuration_version": "1",
        "default_model": client.model,
        "role_models": {role: client.model_for(role) for role in roles},
        "effective_provider_settings": {
            role: resolve_provider(active, client.model_for(role)).summary() for role in roles
        },
        "provider_profile_count": len(active.llm_provider_profiles),
        "response_mode": active.llm_response_mode,
        "token_limit": {"parameter": active.llm_token_limit_parameter, "value": active.max_tokens},
        "temperature": {
            "sent": active.llm_send_temperature,
            "value": active.temperature if active.llm_send_temperature else None,
        },
        "request_budget": {
            "configured_units": active.model_request_budget,
            "effective_ceiling_units": active.model_request_budget or active.max_total_tokens,
        },
        "retries": active.llm_retries,
        "timeout_seconds": active.llm_timeout_seconds,
        "minimum_interval_seconds": active.llm_min_interval_seconds,
        "credentials_configured": {
            "litellm": bool(active.litellm_api_key),
            "openai": bool(active.openai_api_key),
            "anthropic": bool(active.anthropic_api_key),
        },
        "custom_endpoint_configured": bool(active.litellm_api_base),
    }
