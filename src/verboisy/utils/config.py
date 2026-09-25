"""Validated configuration loaded at run time, without import side effects."""

from typing import Any, cast

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    litellm_api_key: SecretStr | None = None
    litellm_api_base: str | None = None
    litellm_model: str = "gpt-4o"
    max_tokens: int = Field(default=4096, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_retries: int = Field(default=2, ge=0, le=5)
    max_total_tokens: int = Field(default=1_000_000, gt=0)
    headless_browser: bool = Field(default=True, validation_alias="VERBOISY_HEADLESS")
    browser_timeout_ms: int = Field(default=30000, gt=0)
    browser_sandbox: bool = True
    user_agent_rotation: bool = True
    allow_private_network: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    sqlite_db_path: str = "verboisy.db"
    log_level: str = Field(default="INFO", validation_alias="VERBOISY_LOG_LEVEL")
    max_steps: int = Field(default=20, gt=0)
    run_timeout_seconds: float = Field(default=900, gt=0)
    action_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    max_dom_chars: int = Field(default=20000, gt=0)
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )


class _LazySettings:
    def __getattr__(self, name: str) -> Any:
        return getattr(Settings(), name)


# Compatibility for low-level integrations. Public run() passes one Settings instance.
settings = cast(Settings, _LazySettings())
