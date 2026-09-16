"""
LiteLLM wrapper client supporting multiple providers.
"""

import json
from typing import Any

from typing import Any, cast

from litellm import completion

from verboisy.utils.config import settings
from verboisy.utils.exceptions import LLMError
from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Client wrapper for LiteLLM to handle completions and structured outputs."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.litellm_model

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """
        Send a completion request and parse the response as JSON.

        Args:
            system_prompt: System instructions.
            user_prompt: User content or context.

        Returns:
            Dict[str, Any]: Parsed JSON response from the LLM.
        """
        logger.debug("Sending LLM completion request", model=self.model)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = completion(
                model=self.model,
                messages=messages,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                response_format={"type": "json_object"},
            )

            content = cast(str | None, response.choices[0].message.content)
            if not content:
                raise LLMError("Received empty response content from LLM model")

            parsed = json.loads(content)
            return cast(dict[str, Any], parsed)
        except Exception as e:
            logger.error("LLM completion failed", model=self.model, error=str(e))
            raise LLMError(f"LLM request failed: {e}", {"model": self.model})
