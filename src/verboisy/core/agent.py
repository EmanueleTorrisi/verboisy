"""
Primary autonomous loop and state machine for Verboisy.
"""

import asyncio
from typing import Any, Dict

from verboisy.utils.logger import get_logger
from verboisy.utils.exceptions import VerboisyError
from verboisy.core.state import AgentState, ActionHistory
from verboisy.core.planner import Planner
from verboisy.browser.context import BrowserManager
from verboisy.extractor.engine import ExtractionEngine
from verboisy.storage.sqlite import DatabaseManager

logger = get_logger(__name__)


class Agent:
    """The central agent orchestrator."""

    def __init__(self, goal: str, target_schema: Dict[str, Any], max_steps: int = 20) -> None:
        self.state = AgentState(goal=goal, target_schema=target_schema, max_steps=max_steps)
        self.browser = BrowserManager()
        self.planner = Planner()
        self.extractor = ExtractionEngine(target_schema)
        self.db = DatabaseManager()

    async def run(self) -> AgentState:
        """
        Execute the autonomous agent loop until the goal is achieved, steps are exhausted, or an error occurs.
        """
        logger.info("Starting Agent Run", run_id=self.state.run_id, goal=self.state.goal)
        self.state.status = "RUNNING"

        await self.db.connect()
        await self.db.save_run(self.state.run_id, self.state.goal, self.state.target_schema, self.state.status)

        try:
            page = await self.browser.start()

            while self.state.step_count < self.state.max_steps:
                self.state.step_count += 1
                current_url = page.url
                self.state.current_url = current_url

                logger.info("Agent Step", step=self.state.step_count, url=current_url)

                html_content = await page.content()

                # 1. Plan next action
                action_req = await self.planner.decide_next_action(
                    goal=self.state.goal,
                    current_url=current_url,
                    html_content=html_content,
                    history=self.state.history
                )

                logger.info("Executing Action", action=action_req.action, parameters=action_req.parameters)

                # 2. Execute action
                if action_req.action == "FINISH":
                    self.state.status = "COMPLETED"
                    logger.info("Agent decided goal is completed")
                    break

                elif action_req.action == "NAVIGATE":
                    url = action_req.parameters.get("url")
                    if not url:
                        raise ValueError("NAVIGATE action requires 'url' parameter")
                    await self.browser.navigate_to(url)

                elif action_req.action == "CLICK":
                    selector = action_req.parameters.get("selector")
                    if not selector:
                        raise ValueError("CLICK action requires 'selector' parameter")
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("networkidle")

                elif action_req.action == "TYPE":
                    selector = action_req.parameters.get("selector")
                    text = action_req.parameters.get("text")
                    if not selector or not text:
                        raise ValueError("TYPE action requires 'selector' and 'text' parameters")
                    await page.fill(selector, text, timeout=5000)
                    await page.keyboard.press("Enter")
                    await page.wait_for_load_state("networkidle")

                elif action_req.action == "EXTRACT":
                    extracted_items = await self.extractor.extract_from_html(html_content)
                    self.state.extracted_data.extend(extracted_items)
                    for item in extracted_items:
                        await self.db.save_extraction(self.state.run_id, current_url, item)

                # 3. Update History
                history_record = ActionHistory(
                    action=action_req.action,
                    parameters=action_req.parameters,
                    url=current_url
                )
                self.state.history.append(history_record)
                await self.db.save_history_action(
                    self.state.run_id, action_req.action, action_req.parameters, current_url
                )

                # Add slight delay to mimic human behavior
                await asyncio.sleep(2)

            if self.state.status != "COMPLETED":
                logger.warning("Max steps reached before FINISH action")
                self.state.status = "COMPLETED"

        except Exception as e:
            logger.error("Agent execution failed", error=str(e))
            self.state.status = "FAILED"
            raise VerboisyError(f"Agent failed during execution: {e}")

        finally:
            await self.db.save_run(self.state.run_id, self.state.goal, self.state.target_schema, self.state.status)
            await self.browser.close()
            await self.db.close()

        return self.state
