"""Planner sees bounded page text, available controls, history, and saved rows."""

import json
from typing import Any

from verboisy.browser.dom_parser import DOMParser
from verboisy.core.state import ActionHistory, ActionRequest
from verboisy.llm.client import LLMClient
from verboisy.llm.prompts import SYSTEM_PLANNER_PROMPT
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, PlanningError


class Planner:
    def __init__(self, llm: LLMClient | None = None, config: Settings | None = None) -> None:
        self.config = config or settings
        self.llm = llm or LLMClient(config=self.config)

    async def decide_next_action(
        self,
        goal: str,
        current_url: str,
        html_content: str,
        history: list[ActionHistory],
        records: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> ActionRequest:
        cleaned = DOMParser.clean_html(html_content)
        records = records or []
        prompt = json.dumps(
            {
                "goal": goal,
                "current_url": current_url,
                "target_schema": schema,
                "history": [h.model_dump(mode="json") for h in history[-10:]],
                "saved_record_count": len(records),
                "recent_records": records[-20:],
                "page_html": cleaned[: self.config.max_dom_chars],
                "page_truncated": len(cleaned) > self.config.max_dom_chars,
                "interactive_elements": DOMParser.extract_interactive_elements(html_content)[
                    :10000
                ],
            },
            ensure_ascii=False,
        )
        try:
            return ActionRequest.model_validate(
                await self.llm.complete_json(SYSTEM_PLANNER_PROMPT, prompt)
            )
        except BudgetExceededError:
            raise
        except Exception as exc:
            raise PlanningError(
                f"Planner failed to generate valid action request ({type(exc).__name__})"
            ) from None
