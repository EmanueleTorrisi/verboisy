"""Async model boundary with bounded retries and explicit credential routing."""

import asyncio
import json
from typing import Any

from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, LLMError


async def _complete(**kwargs: Any) -> Any:
    from litellm import acompletion

    return await acompletion(**kwargs)


class LLMClient:
    def __init__(self, model: str | None = None, config: Settings | None = None) -> None:
        self.config = config or settings
        self.model = model or self.config.litellm_model
        self.total_tokens = 0
        self.reserved_tokens = 0

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
            if self.reserved_tokens + reservation > self.config.max_total_tokens:
                raise BudgetExceededError(
                    "Model request budget exhausted; resume with a larger budget"
                )
            self.reserved_tokens += reservation
            try:
                async with asyncio.timeout(self.config.llm_timeout_seconds):
                    response = await _complete(**kwargs)
                usage = getattr(response, "usage", None)
                tokens = getattr(usage, "total_tokens", 0)
                if isinstance(tokens, int):
                    self.total_tokens += tokens
                content = response.choices[0].message.content
                if getattr(response.choices[0], "finish_reason", None) == "length":
                    raise ValueError("Truncated completion")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty completion")

                def reject_constant(value: str) -> None:
                    raise ValueError(f"Non-JSON constant {value}")

                parsed = json.loads(content, parse_constant=reject_constant)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected a JSON object")
                return parsed
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                transient = isinstance(exc, TimeoutError) or status in (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                )
                if transient and attempt < self.config.llm_retries:
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                raise LLMError(
                    f"LLM request failed ({type(exc).__name__}); "
                    "check provider settings and credentials"
                ) from None
        raise LLMError("LLM request failed")  # pragma: no cover
