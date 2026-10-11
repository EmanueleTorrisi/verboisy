# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit provider capabilities and isolated routing for heterogeneous role models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from verboisy.provider_config import ProviderProfile as ProviderProfile
from verboisy.provider_config import ResponseMode, TokenParameter

if TYPE_CHECKING:
    from verboisy.utils.config import Settings


@dataclass(frozen=True)
class ResolvedProvider:
    prefix: str | None
    api_key: SecretStr | None
    api_base: str | None
    response_mode: ResponseMode
    token_limit_parameter: TokenParameter
    max_tokens: int
    send_temperature: bool

    def request_options(self) -> dict[str, Any]:
        """Construct only supported explicit options at the transport boundary."""
        options: dict[str, Any] = {self.token_limit_parameter: self.max_tokens}
        if self.response_mode == "json_object":
            options["response_format"] = {"type": "json_object"}
        if self.api_key:
            options["api_key"] = self.api_key.get_secret_value()
        if self.api_base:
            options["api_base"] = self.api_base
        return options

    def summary(self) -> dict[str, Any]:
        """Inspection reports routing decisions without key or endpoint values."""
        return {
            "profile_prefix": self.prefix,
            "credentials_configured": bool(self.api_key),
            "custom_endpoint_configured": bool(self.api_base),
            "response_mode": self.response_mode,
            "token_limit": {"parameter": self.token_limit_parameter, "value": self.max_tokens},
            "temperature_sent": self.send_temperature,
        }


def resolve_provider(config: Settings, model: str) -> ResolvedProvider:
    """Use the longest declared prefix, or preserve the legacy routing contract.

    An explicit profile is a credential boundary. A local or third-party model
    must not accidentally receive the global gateway key or gateway endpoint.
    Missing profile credentials are left to the configured provider's own SDK.
    """
    prefix = max(
        (name for name in config.llm_provider_profiles if model.startswith(name)),
        key=len,
        default=None,
    )
    if prefix is not None:
        profile = config.llm_provider_profiles[prefix]
        return ResolvedProvider(
            prefix,
            profile.api_key,
            profile.api_base,
            profile.response_mode,
            profile.token_limit_parameter or config.llm_token_limit_parameter,
            profile.max_tokens if profile.max_tokens is not None else config.max_tokens,
            profile.send_temperature
            if profile.send_temperature is not None
            else config.llm_send_temperature,
        )
    key = config.litellm_api_key
    if key is None:
        if model.startswith(("anthropic/", "claude-")):
            key = config.anthropic_api_key
        elif model.startswith(("openai/", "gpt-", "o1", "o3", "o4")):
            key = config.openai_api_key
    return ResolvedProvider(
        None,
        key,
        config.litellm_api_base,
        config.llm_response_mode,
        config.llm_token_limit_parameter,
        config.max_tokens,
        config.llm_send_temperature,
    )
