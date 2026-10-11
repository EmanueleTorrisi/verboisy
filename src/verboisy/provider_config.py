# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider profile settings without importing clients or provider SDKs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

ResponseMode = Literal["json_object", "prompt"]
TokenParameter = Literal["max_tokens", "max_completion_tokens"]


class ProviderProfile(BaseModel):
    """A prefix-specific request contract; credentials and endpoints never inherit."""

    api_key: SecretStr | None = None
    api_base: str | None = Field(default=None, min_length=1, max_length=8192)
    response_mode: ResponseMode = "json_object"
    token_limit_parameter: TokenParameter | None = None
    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    send_temperature: bool | None = Field(default=None, strict=True)
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
