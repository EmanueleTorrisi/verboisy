"""Planner sees bounded page text, available controls, history, and saved rows."""

import json
from typing import Any

from pydantic import ValidationError

from verboisy.browser.dom_parser import DOMParser
from verboisy.core.state import (
    ActionAttempt,
    ActionFailure,
    ActionHistory,
    ActionRequest,
    SearchObservation,
)
from verboisy.llm.client import LLMClient
from verboisy.llm.prompts import SYSTEM_PLANNER_PROMPT
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, LLMError, PlanningError


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
        *,
        failures: list[ActionFailure] | None = None,
        pending_action: ActionAttempt | None = None,
        search_observation: SearchObservation | None = None,
    ) -> ActionRequest:
        cleaned = DOMParser.clean_html(html_content)
        records = records or []
        prompt = json.dumps(
            {
                "goal": goal,
                "current_url": current_url,
                "target_schema": schema,
                "history": [h.model_dump(mode="json") for h in history[-10:]],
                "action_failures": [f.model_dump(mode="json") for f in (failures or [])[-10:]],
                "interrupted_action": pending_action.model_dump() if pending_action else None,
                "search_provider": self.config.search_provider,
                "search_enabled": self.config.search_provider != "disabled",
                "search_observation": (
                    search_observation.model_dump() if search_observation else None
                ),
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
        # Step 1: Request a structured response from the model.
        try:
            response = await self.llm.complete_json(
                SYSTEM_PLANNER_PROMPT,
                prompt,
            )
        except BudgetExceededError:
            raise
        except LLMError as exc:
            # The model client supplies sanitized diagnostics, not raw provider messages.
            raise PlanningError(f"Planner model call failed: {exc}", details=exc.details) from None
        except Exception as exc:
            raise PlanningError(
                "Planner failed to generate valid action request "
                f"(model response: {type(exc).__name__})"
            ) from None

        # Step 2: Validate the proposed action separately.
        try:
            return ActionRequest.model_validate(response)

        except ValidationError as exc:
            details = ", ".join(
                (f"{'.'.join(str(part) for part in issue['loc']) or 'root'}" f": {issue['type']}")
                for issue in exc.errors(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
            )

            raise PlanningError(
                "Planner failed to generate valid action request "
                f"(action validation: {details or 'unknown validation error'})"
            ) from None

        except Exception as exc:
            raise PlanningError(
                "Planner failed to generate valid action request "
                f"(action validation: {type(exc).__name__})"
            ) from None
