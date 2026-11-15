# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider profile settings without importing clients or provider SDKs."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

ResponseMode = Literal["json_object", "prompt"]
TokenParameter = Literal["max_tokens", "max_completion_tokens"]
ModelRole = Literal["semantic_plan", "source_assessment", "extraction", "escalation"]
PRIMARY_ROLES: tuple[ModelRole, ...] = ("semantic_plan", "source_assessment", "extraction")
ModelTokens = Annotated[int, Field(gt=0, le=4_000_000, strict=True)]
PriceMicros = Annotated[int, Field(ge=0, le=2_000_000_000, strict=True)]


class ProviderProfile(BaseModel):
    """A prefix-specific request contract; credentials and endpoints never inherit."""

    api_key: SecretStr | None = None
    api_base: str | None = Field(default=None, min_length=1, max_length=8192)
    response_mode: ResponseMode = "json_object"
    token_limit_parameter: TokenParameter | None = None
    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    send_temperature: bool | None = Field(default=None, strict=True)
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ApprovedModel(BaseModel):
    """Declared model limits, capabilities, and standard prices for a provider."""

    model: str = Field(min_length=3, max_length=256, pattern=r"^[A-Za-z0-9._:/@+-]+$")
    roles: frozenset[ModelRole] = Field(
        default_factory=lambda: frozenset(PRIMARY_ROLES), min_length=1
    )
    context_tokens: ModelTokens
    max_output_tokens: ModelTokens
    json_object: bool = Field(strict=True)
    input_price_microdollars_per_million: PriceMicros
    output_price_microdollars_per_million: PriceMicros
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @model_validator(mode="after")
    def valid_capacity(self) -> "ApprovedModel":
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("A model must have context for both input and output")
        return self


class ModelRoutingPolicy(BaseModel):
    """Opt in to model selection within a single operator-approved provider."""

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    models: tuple[ApprovedModel, ...] = Field(min_length=1, max_length=64)
    input_tokens_by_role: dict[ModelRole, ModelTokens] = Field(default_factory=dict, max_length=4)
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_catalog(self) -> "ModelRoutingPolicy":
        names = [model.model for model in self.models]
        prefix = self.provider + "/"
        if len(set(names)) != len(names):
            raise ValueError("Approved model identifiers must be unique")
        if any(
            not name.startswith(prefix)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", name[len(prefix) :])
            or "://" in name
            for name in names
        ):
            raise ValueError("Every approved model must name the selected provider explicitly")
        return self
