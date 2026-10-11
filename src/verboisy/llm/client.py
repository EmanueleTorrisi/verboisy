# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Async model boundary with bounded retries and explicit credential routing."""

import asyncio
import inspect
import json
import time
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from pydantic import ValidationError

from verboisy.llm.diagnostics import provider_failure_message
from verboisy.llm.providers import resolve_provider
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import (
    BudgetExceededError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
)


class _InvalidResponseError(ValueError):
    """Provider returned content that cannot satisfy the JSON contract."""


async def _complete(**kwargs: Any) -> Any:
    import logging
    import os

    os.environ.setdefault("LITELLM_LOG", "ERROR")

    import litellm

    litellm.suppress_debug_info = True

    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM").propagate = False
    logging.getLogger("litellm").setLevel(logging.ERROR)
    logging.getLogger("litellm").propagate = False

    return await litellm.acompletion(**kwargs)


ModelRole = Literal[
    "semantic_plan",
    "source_assessment",
    "extraction",
    "escalation",
]

T = TypeVar("T")


async def complete_json_for_role(
    client: Any,
    role: ModelRole,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Route by role when the active client method supports model overrides."""

    complete = client.complete_json

    try:
        supports_model = "model" in inspect.signature(complete).parameters
    except (TypeError, ValueError):
        supports_model = False

    model_for = getattr(
        type(client),
        "model_for",
        None,
    )

    if callable(model_for) and supports_model:
        result = await complete(
            system_prompt,
            user_prompt,
            model=client.model_for(role),
        )
    else:
        # Compatibility with lightweight clients and tests that
        # monkeypatch LLMClient.complete_json using the legacy
        # (system_prompt, user_prompt) contract.
        result = await complete(
            system_prompt,
            user_prompt,
        )

    return cast(
        dict[str, Any],
        result,
    )


def escalation_available(
    client: Any,
    role: ModelRole,
) -> bool:
    """Return whether a distinct configured escalation model can be used."""

    config = getattr(
        client,
        "config",
        None,
    )

    configured = getattr(
        config,
        "escalation_model",
        None,
    )

    if not isinstance(configured, str) or not configured:
        return False

    model_for = getattr(
        type(client),
        "model_for",
        None,
    )

    if not callable(model_for):
        return False

    complete = getattr(
        client,
        "complete_json",
        None,
    )

    if complete is None:
        return False

    try:
        supports_model = "model" in inspect.signature(complete).parameters
    except (TypeError, ValueError):
        return False

    if not supports_model:
        return False

    role_model = cast(
        str,
        client.model_for(role),
    )
    escalation_model = cast(
        str,
        client.model_for("escalation"),
    )

    return role_model != escalation_model


async def complete_validated_for_role(
    client: Any,
    role: ModelRole,
    system_prompt: str,
    user_prompt: str,
    validator: Any,
) -> T:
    """Validate a role response and escalate once only for contract failure."""

    try:
        response = await complete_json_for_role(
            client,
            role,
            system_prompt,
            user_prompt,
        )

        return cast(
            T,
            validator(response),
        )

    except (
        LLMResponseError,
        ValidationError,
    ) as exc:
        if not escalation_available(
            client,
            role,
        ):
            raise

        primary_model = cast(
            str,
            client.model_for(role),
        )
        escalation_model = cast(
            str,
            client.model_for("escalation"),
        )

        reason = (
            "invalid_model_response"
            if isinstance(
                exc,
                LLMResponseError,
            )
            else "validation_error"
        )

        on_escalation = getattr(
            client,
            "on_escalation",
            None,
        )

        if callable(on_escalation):
            on_escalation(
                {
                    "role": role,
                    "reason": reason,
                    "primary_model": primary_model,
                    "escalation_model": escalation_model,
                }
            )

    response = await complete_json_for_role(
        client,
        "escalation",
        system_prompt,
        user_prompt,
    )

    return cast(
        T,
        validator(response),
    )


class LLMClient:
    def __init__(self, model: str | None = None, config: Settings | None = None) -> None:
        self.config = config or settings
        self.model = model or self.config.litellm_model
        self.total_tokens = 0
        self.reserved_tokens = 0
        self.search_requests = 0
        self.last_request = 0.0
        self.on_usage: Callable[[], None] | None = None
        self.on_escalation: Callable[[dict[str, str]], None] | None = None

    def reserve_request(self, amount: int) -> None:
        """Reserve shared request units and persist through the runner's usage hook."""
        ceiling = self.config.model_request_budget or self.config.max_total_tokens
        if self.reserved_tokens + amount > ceiling:
            raise BudgetExceededError("Model request budget exhausted; resume with a larger budget")
        # Reserve before transport: a failed attempt still consumes the local budget.
        # Provider-reported tokens are tracked separately; this is not a billing estimate.
        self.reserved_tokens += amount
        if self.on_usage:
            self.on_usage()

    def report_tokens(self, amount: int) -> None:
        self.total_tokens += amount
        if self.on_usage:
            self.on_usage()

    def model_for(
        self,
        role: ModelRole,
    ) -> str:
        """Resolve a task model without creating another client."""

        configured = getattr(
            self.config,
            f"{role}_model",
            None,
        )

        if isinstance(configured, str) and configured:
            return configured

        return self.model

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        request_model = model or self.model
        provider = resolve_provider(self.config, request_model)

        messages = [
            {
                "role": "system",
                "content": system_prompt
                + (
                    "\n\nReturn a single valid JSON object. "
                    "Do not include Markdown fences or commentary."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]
        # Local request budget, not a billing guarantee: provider hidden tokens may differ.
        reservation = len(json.dumps(messages, ensure_ascii=False).encode()) + provider.max_tokens
        kwargs: dict[str, Any] = {
            "model": request_model,
            "messages": messages,
            **provider.request_options(),
            "timeout": self.config.llm_timeout_seconds,
            "num_retries": 0,
        }
        if provider.send_temperature:
            kwargs["temperature"] = self.config.temperature
        for attempt in range(self.config.llm_retries + 1):
            ceiling = self.config.model_request_budget or self.config.max_total_tokens
            if self.reserved_tokens + reservation > ceiling:
                raise BudgetExceededError(
                    "Model request budget exhausted; resume with a larger budget"
                )
            remaining = self.config.llm_min_interval_seconds - (
                time.monotonic() - self.last_request
            )
            if remaining > 0:
                await asyncio.sleep(remaining)
            self.last_request = time.monotonic()
            self.reserve_request(reservation)
            try:
                async with asyncio.timeout(self.config.llm_timeout_seconds):
                    response = await _complete(**kwargs)
                usage = getattr(response, "usage", None)
                tokens = getattr(usage, "total_tokens", 0)
                if isinstance(tokens, int):
                    self.total_tokens += tokens
                    if self.on_usage:
                        self.on_usage()
                content = response.choices[0].message.content
                if getattr(response.choices[0], "finish_reason", None) == "length":
                    raise _InvalidResponseError("truncated")
                if not isinstance(content, str) or not content.strip():
                    raise _InvalidResponseError("empty")

                def reject_constant(_value: str) -> None:
                    raise _InvalidResponseError("non_json_constant")

                try:
                    parsed = json.loads(content, parse_constant=reject_constant)
                except json.JSONDecodeError as exc:
                    raise _InvalidResponseError("invalid_json") from exc

                if not isinstance(parsed, dict):
                    raise _InvalidResponseError("not_object")
                return parsed
            except Exception as exc:
                response = getattr(exc, "response", None)
                status = getattr(exc, "status_code", None)

                if status is None and response is not None:
                    status = getattr(response, "status_code", None)

                if isinstance(exc, _InvalidResponseError):
                    if attempt < self.config.llm_retries:
                        continue
                    raise LLMResponseError("LLM returned invalid or incomplete JSON") from None

                detail = str(exc).lower()
                code = str(getattr(exc, "code", "") or "").lower()

                quota_markers = (
                    "insufficient_quota",
                    "credit_balance_exhausted",
                    "exceeded your current quota",
                    "billing hard limit",
                    "tokens per day",
                    "daily limit",
                    "project_spend_limit_exceeded",
                )

                if status == 429 and any(
                    marker in detail or marker in code for marker in quota_markers
                ):
                    raise LLMError(
                        "OpenAI quota or daily limit reached "
                        "(HTTP 429). Check API usage and billing."
                    ) from None

                if status == 429:
                    raise LLMRateLimitError("OpenAI rate limit reached") from None

                transient = isinstance(exc, TimeoutError) or status in (
                    408,
                    500,
                    502,
                    503,
                    504,
                )

                if transient and attempt < self.config.llm_retries:
                    import random

                    delay = min(2**attempt, 8) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                    continue

                raise LLMError(provider_failure_message(exc, status)) from None
        raise LLMError("LLM request failed")  # pragma: no cover
