"""Checkpointed research loop. Only FINISH can complete a run."""

import asyncio
from typing import Any
from urllib.parse import quote_plus, urlsplit

from verboisy.browser.actions import interact
from verboisy.browser.context import BrowserManager
from verboisy.browser.policy import validate_url
from verboisy.core.planner import Planner
from verboisy.core.search import brave_search
from verboisy.core.state import (
    ActionAttempt,
    ActionFailure,
    ActionHistory,
    ActionRequest,
    AgentState,
)
from verboisy.extractor.engine import ExtractionEngine
from verboisy.llm.client import LLMClient
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import (
    BrowserActionError,
    BudgetExceededError,
    SearchUnavailableError,
    VerboisyError,
)
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

        elif action == "NAVIGATE":
            await self.browser.navigate_to(parameters["url"])
        elif action == "SEARCH":
            self.state.search_observation = None
            if self.config.search_provider == "disabled":
                raise SearchUnavailableError("SEARCH is disabled. Use a known source URL.")
            if self.config.search_provider == "brave":
                self.state.search_observation = await brave_search(parameters["query"], self.config)
            else:
                await self.browser.navigate_to(
                    "https://www.google.com/search?q=" + quote_plus(parameters["query"])
                )
                final_url = urlsplit(page.url)
                if final_url.hostname in {"google.com", "www.google.com"}:
                    content = (await page.content()).lower()
                    if (
                        final_url.path.startswith("/sorry")
                        or "unusual traffic from your computer" in content
                    ):
                        raise SearchUnavailableError(
                            "Search provider unavailable: Google returned "
                            "an automated-traffic warning. No search results were obtained. "
                            "Configure SEARCH_PROVIDER=brave with BRAVE_SEARCH_API_KEY, "
                            "or start a direct-source run with SEARCH_PROVIDER=disabled."
                        )
        elif action in ("CLICK", "TYPE", "CHECK", "SELECT"):
            await interact(page, request, self.config.browser_action_timeout_ms)
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
        action_failures = 0
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
                        failures=self.state.action_failures,
                        pending_action=self.state.pending_action,
                        search_observation=self.state.search_observation,
                    )
                    attempt = ActionAttempt(
                        step=self.state.step_count,
                        action=request.action,
                        selector=request.parameters.get("selector"),
                        url=page.url,
                    )
                    self.state.pending_action = attempt
                    self.state.token_count = token_start + self.llm.total_tokens
                    await self.db.checkpoint(self.state)
                    logger.info("ACT", **attempt.model_dump())
                    saved_before = len(self.state.extracted_data)
                    try:
                        await self._execute(request, html)
                    except (BrowserActionError, SearchUnavailableError) as exc:
                        self.state.current_url = page.url
                        failure = ActionFailure(
                            **attempt.model_dump(),
                            error_type=exc.details.get("error_type", type(exc).__name__),
                            message=str(exc),
                        )
                        self.state.action_failures = [*self.state.action_failures, failure][-10:]
                        self.state.pending_action = None
                        logger.warning("ACTION_FAILED", **failure.model_dump())
                        action_failures += 1
                        if isinstance(exc, SearchUnavailableError):
                            self.state.status = "PAUSED"
                            self.state.stop_reason = "search_unavailable"
                        elif action_failures >= self.config.max_action_failures:
                            self.state.status = "PAUSED"
                            self.state.stop_reason = "action_failures"
                        await self.db.checkpoint(self.state)
                        if self.state.status == "PAUSED":
                            break
                        # A failed interaction may have partly executed; observe before replanning.
                        await asyncio.sleep(self.config.action_delay_seconds)
                        continue
                    self.state.pending_action = None
                    history_parameters = dict(request.parameters)
                    if request.action == "EXTRACT":
                        saved_now = len(self.state.extracted_data) - saved_before
                        history_parameters["saved_records"] = saved_now
                        logger.info(
                            "EXTRACT_RESULT",
                            run_id=self.state.run_id,
                            saved_records=saved_now,
                            total_records=len(self.state.extracted_data),
                        )
                    history = ActionHistory(
                        action=request.action, parameters=history_parameters, url=page.url
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
