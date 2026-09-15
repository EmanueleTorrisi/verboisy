"""
Configuration management using Pydantic BaseSettings.
"""

from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Settings
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    litellm_model: str = "gpt-4o"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Browser Settings
    headless_browser: bool = Field(default=True, validation_alias="VERBOISY_HEADLESS")
    browser_timeout_ms: int = 30000
    user_agent_rotation: bool = True

    # Application State / Storage
    sqlite_db_path: str = "verboisy.db"
    log_level: str = Field(default="INFO", validation_alias="VERBOISY_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Global singleton settings object
settings = Settings()
