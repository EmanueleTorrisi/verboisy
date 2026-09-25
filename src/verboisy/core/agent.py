"""Checkpointed research loop. Only FINISH can complete a run."""

import asyncio
from typing import Any
from urllib.parse import quote_plus

from verboisy.browser.context import BrowserManager
from verboisy.browser.policy import validate_url
from verboisy.core.planner import Planner
from verboisy.core.state import ActionHistory, ActionRequest, AgentState
from verboisy.extractor.engine import ExtractionEngine
from verboisy.llm.client import LLMClient
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, VerboisyError
from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class Agent:
    def __init__(
        self,
        goal: str,
        target_schema: dict[str, Any],
        max_steps: int = 20,
        *,
        config: Settings | None = None,
        state: AgentState | None = None,
        db: DatabaseManager | None = None,
    ) -> None:
        self.config = config or settings
        self.state = state or AgentState(
            goal=goal, target_schema=target_schema, max_steps=max_steps
        )
        self.state.max_steps = max_steps
        self.llm = LLMClient(config=self.config)
        self.browser = BrowserManager(config=self.config)
        self.planner = Planner(llm=self.llm, config=self.config)
        self.extractor = ExtractionEngine(target_schema, llm=self.llm, config=self.config)
        self.db = db or DatabaseManager(self.config.sqlite_db_path)

    async def _execute(self, request: ActionRequest, html: str) -> None:
        page = await self.browser.get_page()
        parameters = request.parameters
        action = request.action
        if action == "FINISH":
            self.extractor.validate_collection(self.state.extracted_data)
            self.state.status = "COMPLETED"
            self.state.stop_reason = "planner_finished"
        elif action in ("NAVIGATE", "SEARCH"):
            url = (
                parameters["url"]
                if action == "NAVIGATE"
                else ("https://www.google.com/search?q=" + quote_plus(parameters["query"]))
            )
            await self.browser.navigate_to(url)
        elif action == "CLICK":
            await page.click(parameters["selector"])
            await page.wait_for_load_state("domcontentloaded")
        elif action == "TYPE":
            await page.fill(parameters["selector"], parameters["text"])
            if parameters.get("submit", True):
                await page.press(parameters["selector"], "Enter")
                await page.wait_for_load_state("domcontentloaded")
        elif action == "SCROLL":
            await page.mouse.wheel(0, parameters.get("pixels", 700))
        elif action == "WAIT":
            await asyncio.sleep(parameters.get("milliseconds", 1000) / 1000)
        elif action == "EXTRACT":
            async for item in self.extractor.iter_from_html(html, self.state.goal):
                if await self.db.save_extraction(self.state.run_id, page.url, item):
                    self.state.extracted_data.append(item)
                    logger.info(
                        "SAVE", run_id=self.state.run_id, records=len(self.state.extracted_data)
                    )
        else:
            raise VerboisyError(f"Unsupported action: {action}")
        if page.url != "about:blank":
            await validate_url(page.url, self.config)
        self.state.current_url = page.url

    async def run(self) -> AgentState:
        token_start = self.state.token_count
        error_active = False
        try:
            self.db.acquire_run_lock()
            await self.db.connect()
            self.state.status = "RUNNING"
            self.state.stop_reason = None
            await self.db.checkpoint(self.state)
            logger.info(
                "RUN", run_id=self.state.run_id, saved_records=len(self.state.extracted_data)
            )
            async with asyncio.timeout(self.config.run_timeout_seconds):
                page = await self.browser.start()
                if self.state.current_url and self.state.current_url != "about:blank":
                    await self.browser.navigate_to(self.state.current_url)
                for _ in range(self.state.max_steps):
                    self.state.step_count += 1
                    self.state.current_url = page.url
                    if page.url != "about:blank":
                        await validate_url(page.url, self.config)
                    html = await page.content()
                    request = await self.planner.decide_next_action(
                        self.state.goal,
                        page.url,
                        html,
                        self.state.history,
                        records=self.state.extracted_data,
                        schema=self.state.target_schema,
                    )
                    logger.info("ACT", action=request.action, step=self.state.step_count)
                    await self._execute(request, html)
                    history = ActionHistory(
                        action=request.action, parameters=request.parameters, url=page.url
                    )
                    self.state.history.append(history)
                    self.state.token_count = token_start + self.llm.total_tokens
                    await self.db.checkpoint(self.state, history)
                    if request.action == "FINISH":
                        break
                    await asyncio.sleep(self.config.action_delay_seconds)
                else:
                    self.state.status = "PAUSED"
                    self.state.stop_reason = "max_steps"
        except (BudgetExceededError, TimeoutError) as exc:
            self.state.status = "PAUSED"
            self.state.stop_reason = (
                "model_budget" if isinstance(exc, BudgetExceededError) else "run_timeout"
            )
        except asyncio.CancelledError:
            error_active = True
            self.state.status = "INTERRUPTED"
            self.state.stop_reason = "cancelled"
            raise
        except Exception as exc:
            error_active = True
            self.state.status = "FAILED"
            self.state.stop_reason = type(exc).__name__
            detail = str(exc) if isinstance(exc, VerboisyError) else type(exc).__name__
            raise VerboisyError(
                f"Run {self.state.run_id} failed: {detail}. "
                f"Committed records remain in {self.db.db_path}; use --resume {self.state.run_id}."
            ) from exc
        finally:
            self.state.token_count = token_start + self.llm.total_tokens
            try:
                # Do not overwrite another worker's state when lock acquisition failed.
                if self.db._lock is not None and self.db._conn is not None:
                    try:
                        await self.db.checkpoint(self.state)
                    except Exception:
                        if not error_active:
                            raise
                        logger.error("Final checkpoint failed; earlier commits remain durable")
            finally:
                try:
                    await self.browser.close()
                finally:
                    await self.db.close()
        return self.state
