"""Async model boundary with bounded retries and explicit credential routing."""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC
from typing import Any

from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, LLMError, LLMResponseError


class _InvalidResponseError(ValueError):
    """Provider returned content that cannot satisfy the JSON contract."""


async def _complete(**kwargs: Any) -> Any:
    from litellm import acompletion

    return await acompletion(**kwargs)


class LLMClient:
    def __init__(self, model: str | None = None, config: Settings | None = None) -> None:
        self.config = config or settings
        self.model = model or self.config.litellm_model
        self.total_tokens = 0
        self.reserved_tokens = 0
        self.last_request = 0.0
        self.on_usage: Callable[[], None] | None = None

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # Local request budget, not a billing guarantee: provider hidden tokens may differ.
        reservation = (
            len(json.dumps(messages, ensure_ascii=False).encode()) + self.config.max_tokens
        )
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "timeout": self.config.llm_timeout_seconds,
            "num_retries": 0,
        }
        key = self.config.litellm_api_key
        if key is None:
            if self.model.startswith(("anthropic/", "claude-")):
                key = self.config.anthropic_api_key
            elif self.model.startswith(("openai/", "gpt-", "o1", "o3", "o4")):
                key = self.config.openai_api_key
        if key:
            kwargs["api_key"] = key.get_secret_value()
        if self.config.litellm_api_base:
            kwargs["api_base"] = self.config.litellm_api_base
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
            self.reserved_tokens += reservation
            if self.on_usage:
                self.on_usage()
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
                import math
                import random
                import sys
                from datetime import datetime
                from email.utils import parsedate_to_datetime

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

                transient = isinstance(exc, TimeoutError) or status in (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                )

                if transient and attempt < self.config.llm_retries:
                    if status == 429:
                        headers = (
                            getattr(response, "headers", None)
                            or getattr(exc, "headers", None)
                            or {}
                        )

                        retry_after = next(
                            (
                                value
                                for name, value in headers.items()
                                if str(name).lower() == "retry-after"
                            ),
                            None,
                        )

                        delay = None

                        if retry_after is not None:
                            try:
                                delay = float(retry_after)

                            except (TypeError, ValueError):
                                try:
                                    retry_at = parsedate_to_datetime(str(retry_after))

                                    if retry_at.tzinfo is None:
                                        retry_at = retry_at.replace(tzinfo=UTC)

                                    delay = (retry_at - datetime.now(UTC)).total_seconds()

                                except (
                                    TypeError,
                                    ValueError,
                                    OverflowError,
                                ):
                                    delay = None

                        if delay is None or not math.isfinite(delay):
                            delay = min(
                                60.0,
                                15.0 * (2**attempt) + random.uniform(0, 3),
                            )

                        delay = max(1.0, delay)

                        if delay > 120:
                            raise LLMError(
                                "OpenAI requested a retry delay "
                                "longer than two minutes. "
                                "Resume after the limit resets."
                            ) from None

                        print(
                            "OpenAI HTTP 429: retry "
                            f"{attempt + 1}/"
                            f"{self.config.llm_retries} "
                            f"after {delay:.1f} seconds",
                            file=sys.stderr,
                        )

                    else:
                        delay = min(2**attempt, 8) + random.uniform(0, 1)

                    await asyncio.sleep(delay)
                    continue

                raise LLMError(
                    f"LLM request failed "
                    f"({type(exc).__name__}, HTTP {status}); "
                    "check provider limits and configuration"
                ) from None
        raise LLMError("LLM request failed")  # pragma: no cover
