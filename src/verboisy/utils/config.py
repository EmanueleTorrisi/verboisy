# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validated configuration loaded at run time, without import side effects."""

from typing import Any, Literal, cast

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from verboisy.presentation_config import (
    DateFormat,
    LengthUnit,
    MassUnit,
    PresentationPreferences,
    preferences,
)
from verboisy.provider_config import ProviderProfile, ResponseMode
from verboisy.source_config import validate_http_headers


class Settings(BaseSettings):
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    litellm_api_key: SecretStr | None = None
    litellm_api_base: str | None = None
    litellm_model: str = "gpt-4o"
    semantic_plan_model: str | None = None
    source_assessment_model: str | None = None
    extraction_model: str | None = None
    escalation_model: str | None = None
    max_tokens: int = Field(default=4096, gt=0)
    llm_token_limit_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    llm_response_mode: ResponseMode = "json_object"
    llm_provider_profiles: dict[str, ProviderProfile] = Field(default_factory=dict, max_length=64)
    temperature: float = Field(default=0.0, ge=0, le=2)
    llm_send_temperature: bool = True
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_retries: int = Field(default=2, ge=0, le=5)
    max_total_tokens: int = Field(default=1_000_000, gt=0)
    headless_browser: bool = Field(default=True, validation_alias="VERBOISY_HEADLESS")
    browser_timeout_ms: int = Field(default=30000, gt=0)
    browser_action_timeout_ms: int = Field(default=10000, gt=0)
    max_action_failures: int = Field(default=3, ge=1, le=20)
    search_provider: Literal["auto", "openai", "brave", "disabled"] = "auto"
    brave_search_api_key: SecretStr | None = None
    search_timeout_seconds: float = Field(default=30, gt=0)
    openai_search_model: str = "gpt-4.1-mini"
    browser_auto_install: bool = True
    max_page_bytes: int = Field(default=5_000_000, ge=1000, le=50_000_000)
    max_snapshot_chars: int = Field(default=120000, ge=1000, le=2000000)
    llm_min_interval_seconds: float = Field(default=1, ge=0, le=120)
    search_request_budget: int | None = Field(default=None, ge=0)
    model_request_budget: int | None = Field(default=None, gt=0)
    browser_sandbox: bool = True
    user_agent_rotation: bool = False
    allow_private_network: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    dataset_local_roots: list[str] = Field(default_factory=list, max_length=64)
    dataset_http_headers: dict[str, dict[str, SecretStr]] = Field(
        default_factory=dict, max_length=64
    )
    sqlite_db_path: str = "verboisy.db"
    display_mass_unit: MassUnit = Field(default="kg", validation_alias="VERBOISY_MASS_UNIT")
    display_length_unit: LengthUnit = Field(default="m", validation_alias="VERBOISY_LENGTH_UNIT")
    display_date_format: DateFormat = Field(default="dmy", validation_alias="VERBOISY_DATE_FORMAT")
    log_level: str = Field(default="INFO", validation_alias="VERBOISY_LOG_LEVEL")
    max_steps: int = Field(default=20, gt=0)
    run_timeout_seconds: float = Field(default=900, gt=0)
    action_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    max_dom_chars: int = Field(default=20000, gt=0)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    @field_validator("llm_provider_profiles")
    @classmethod
    def valid_provider_prefixes(
        cls, value: dict[str, ProviderProfile]
    ) -> dict[str, ProviderProfile]:
        import re

        if any(not re.fullmatch(r"[A-Za-z0-9._:/-]{1,256}", prefix) for prefix in value):
            raise ValueError("Provider prefixes must be nonempty model identifier prefixes")
        return value

    @field_validator("dataset_local_roots")
    @classmethod
    def absolute_local_roots(cls, value: list[str]) -> list[str]:
        from pathlib import Path

        if any(not root or not Path(root).is_absolute() for root in value):
            raise ValueError("Dataset local roots must be absolute paths")
        return value

    @field_validator("dataset_http_headers")
    @classmethod
    def scoped_dataset_credentials(
        cls, value: dict[str, dict[str, SecretStr]]
    ) -> dict[str, dict[str, SecretStr]]:
        return validate_http_headers(value)

    def presentation_defaults(self) -> PresentationPreferences:
        """Validate display defaults before any run opens or mutates its ledger."""
        return preferences(
            {
                "mass_unit": self.display_mass_unit,
                "length_unit": self.display_length_unit,
                "date_format": self.display_date_format,
            }
        )


class _LazySettings:
    def __getattr__(self, name: str) -> Any:
        return getattr(Settings(), name)


# Compatibility for low-level integrations. Public run() passes one Settings instance.
settings = cast(Settings, _LazySettings())
