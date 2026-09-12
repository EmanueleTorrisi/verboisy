"""
LLM-driven decision-making engine for the agent.
"""

from typing import Dict, Any, List

from verboisy.utils.logger import get_logger
from verboisy.utils.exceptions import PlanningError
from verboisy.llm.client import LLMClient
from verboisy.llm.prompts import SYSTEM_PLANNER_PROMPT
from verboisy.core.state import ActionRequest, ActionHistory
from verboisy.browser.dom_parser import DOMParser


logger = get_logger(__name__)


class Planner:
    """Interprets the current state and DOM to decide the next action."""

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def decide_next_action(
        self,
        goal: str,
        current_url: str,
        html_content: str,
        history: List[ActionHistory]
    ) -> ActionRequest:
        """
        Analyze current state and formulate the next discrete action.

        Args:
            goal: The overarching user objective.
            current_url: The URL currently loaded in the browser.
            html_content: The raw HTML of the current page.
            history: List of past actions taken in this run.

        Returns:
            ActionRequest: The validated Pydantic model for the next action.
        """
        logger.debug("Planning next action", current_url=current_url)

        # Extract interactive elements for context
        interactive_elements = DOMParser.extract_interactive_elements(html_content)

        # Serialize history safely
        history_summary = "\n".join(
            [f"- {h.action} | {h.parameters} @ {h.url}" for h in history[-5:]] # Keep last 5 for context limits
        )

        user_prompt = f"""
        GOAL: {goal}
        CURRENT URL: {current_url}

        RECENT HISTORY:
        {history_summary if history_summary else "No previous actions taken."}

        AVAILABLE INTERACTIVE ELEMENTS:
        {interactive_elements if interactive_elements else "No obvious interactive elements found."}

        Based on the current state, determine the single next best action to progress towards the goal.
        """

        try:
            response_json = await self.llm.complete_json(SYSTEM_PLANNER_PROMPT, user_prompt)
            return ActionRequest.model_validate(response_json)
        except Exception as e:
            logger.error("Failed to generate plan", error=str(e))
            raise PlanningError(f"Planner failed to generate valid action request: {e}")
