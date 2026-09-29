"""Persisted breadth-first traversal. A model cannot declare a run complete."""

import asyncio
import fnmatch
import json
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from verboisy.browser.context import BrowserManager
from verboisy.evidence.models import Snapshot, TaskSpec
from verboisy.evidence.snapshot import canonical_url, chunks, snapshot
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import (
    BudgetExceededError,
    LLMError,
    LLMResponseError,
    NavigationError,
)

CAPTURE_PAGE = """maxBytes => {
 const url=location.href, html=document.documentElement.outerHTML;
 if(new TextEncoder().encode(html).length > maxBytes) return {oversized:true};
 const copy=document.documentElement.cloneNode(true);
 const originals=[...document.documentElement.querySelectorAll('*')];
 const clones=[...copy.querySelectorAll('*')];
 originals.forEach((el,i)=>{ const s=getComputedStyle(el);
  if(s.display==='none'||s.visibility==='hidden'||el.hidden)
   clones[i].setAttribute('hidden',''); });
 return {url,html,visible_html:copy.outerHTML,oversized:false};
}"""


class ResearchRunner:
    def __init__(self, store: ResearchStore, rid: str, config: Settings):
        self.store, self.rid, self.config = store, rid, config
        row = store.load(rid)
        self.task = TaskSpec.model_validate_json(row["task_json"])
        self.schema = json.loads(row["schema_json"])
        self.client = LLMClient(config=config)
        self.client.total_tokens, self.client.reserved_tokens = row["tokens"], row["reserved"]
        self.client.on_usage = self.account
        self.extractor = EvidenceExtractor(self.client, self.schema, self.task, row["goal"])
        self.browser = BrowserManager(config=config)
        self.hosts = {h.lower().rstrip(".") for h in self.task.allowed_hosts} or {
            str(urlsplit(u).hostname).lower().rstrip(".") for u in self.task.seed_urls
        }

    def account(self) -> None:
        self.store.finish(
            self.rid, "RUNNING", "running", self.client.total_tokens, self.client.reserved_tokens
        )

    def in_scope(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        return (
            str(parsed.hostname).lower().rstrip(".") in self.hosts
            and (
                not self.task.include_paths
                or any(fnmatch.fnmatchcase(path, p) for p in self.task.include_paths)
            )
            and not any(fnmatch.fnmatchcase(path, p) for p in self.task.exclude_paths)
        )

    def target_met(self) -> bool:
        rows = self.store.records(self.rid)
        if (
            self.store.summary(self.rid)["identity_conflicts"]
            or self.task.target_records is None
            or len(rows) != self.task.target_records
        ):
            return False
        return self.schema["type"] != "array" or bool(
            SchemaBuilder.validator(self.schema).is_valid(rows)
        )

    def discover(self, page: Snapshot, depth: int, priorities: list[str]) -> None:
        urls = list(
            dict.fromkeys(
                s.href
                for s in sorted(page.sources, key=lambda s: s.id not in priorities)
                if s.href and self.in_scope(s.href)
            )
        )
        for url in urls[: self.task.max_links_per_page]:
            self.store.queue(self.rid, url, depth + 1, page.url)
        if len(urls) > self.task.max_links_per_page or page.truncated:
            self.store.event(
                self.rid, "coverage_gap", {"page": page.id, "reason": "snapshot_or_link_limit"}
            )

    async def process(self, work: dict[str, Any]) -> None:
        if not self.in_scope(work["url"]):
            self.store.mark_page(work["id"], "blocked", "scope_limit")
            return
        await self.browser.navigate_to(work["url"])
        page = await self.browser.get_page()
        seen: set[str] = set()
        interaction = 0
        while True:
            await asyncio.sleep(self.task.settle_ms / 1000)
            observation = await page.evaluate(CAPTURE_PAGE, self.config.max_page_bytes)
            if observation["oversized"]:
                raise NavigationError("Page exceeds configured size limit")
            url = canonical_url(observation["url"])
            if url is None or not self.in_scope(url):
                raise NavigationError("Redirect left the declared crawl scope")
            html, visible_html = observation["html"], observation["visible_html"]
            if len(html.encode()) > self.config.max_page_bytes:
                raise NavigationError("Page exceeds configured size limit")
            captured = snapshot(visible_html, url, self.config.max_snapshot_chars)
            # Compare evidence, not volatile resource attributes or timestamps.
            signature = json.dumps([s.model_dump() for s in captured.sources], sort_keys=True)
            if signature in seen:
                break
            seen.add(signature)
            self.store.snapshot(self.rid, work["id"], captured, html, visible_html)
            priorities: list[str] = []
            try:
                batches = chunks(captured, self.config.max_dom_chars)
            except ValueError:
                self.store.event(self.rid, "coverage_gap", {"reason": "oversized_evidence_block"})
                batches = []
            for batch in batches:
                try:
                    proposal = await self.extractor.propose(captured, batch)
                except ValidationError:
                    self.store.event(self.rid, "coverage_gap", {"reason": "invalid_proposal"})
                    continue
                except LLMResponseError:
                    self.store.event(
                        self.rid,
                        "coverage_gap",
                        {"reason": "invalid_model_response"},
                    )
                    continue
                priorities.extend(proposal.priority_links)
                supplied = captured.model_copy(update={"sources": batch})
                for candidate in proposal.candidates:
                    try:
                        errors = await self.extractor.check(candidate, supplied)
                    except ValidationError:
                        errors = ["invalid_review"]
                    except LLMResponseError:
                        self.store.event(
                            self.rid,
                            "coverage_gap",
                            {"reason": "invalid_review_response"},
                        )
                        errors = ["invalid_review"]
                    outcome = self.store.accept(self.rid, captured, candidate, errors, self.task)
                    self.store.event(self.rid, "candidate", {"outcome": outcome, "reasons": errors})
                    if self.target_met():
                        self.discover(captured, work["depth"], priorities)
                        self.store.mark_page(work["id"], "done")
                        return
            self.discover(captured, work["depth"], priorities)
            selector = self.task.pagination_selector
            if not selector:
                break
            control = page.locator(selector)
            if (
                await control.count() != 1
                or not await control.is_visible()
                or not await control.is_enabled()
            ):
                break
            if interaction == self.task.max_interactions_per_page:
                self.store.event(
                    self.rid, "coverage_gap", {"reason": "interaction_limit", "url": url}
                )
                break
            await control.click(timeout=self.config.browser_action_timeout_ms)
            interaction += 1
        self.store.mark_page(work["id"], "done")

    async def run(self, max_steps: int) -> tuple[str, str]:
        self.store.recover(self.rid)
        status, reason = "PAUSED", "page_budget"
        try:
            await self.browser.start()
            async with asyncio.timeout(self.config.run_timeout_seconds):
                for _ in range(max_steps):
                    if self.target_met():
                        status, reason = "COMPLETED", "target_met"
                        break
                    summary = self.store.summary(self.rid)
                    if (
                        sum(summary["pages"].get(s, 0) for s in ("done", "blocked"))
                        >= self.task.max_pages
                    ):
                        break
                    work = self.store.next_page(self.rid)
                    if work is None:
                        if summary["pages"].get("failed"):
                            status, reason = "FAILED", "source_failures"
                        elif (
                            summary["pages"].get("blocked")
                            or summary["coverage_gaps"]
                            or summary["identity_conflicts"]
                        ):
                            status, reason = "PAUSED", "coverage_or_identity_gaps"
                        else:
                            status, reason = "EXHAUSTED", "observed_scope_exhausted"
                        break
                    if work["depth"] > self.task.max_depth:
                        self.store.mark_page(work["id"], "blocked", "depth_limit")
                        continue
                    try:
                        await self.process(work)
                    except NavigationError:
                        self.store.mark_page(work["id"], "failed", "navigation_failed")
                        self.store.event(self.rid, "page_failure", {"page_id": work["id"]})
                    if self.target_met():
                        status, reason = "COMPLETED", "target_met"
                        break
                    await asyncio.sleep(self.config.action_delay_seconds)
        except BudgetExceededError:
            reason = "model_request_budget"
        except TimeoutError:
            reason = "run_timeout"
        except LLMError as exc:
            status, reason = "FAILED", str(exc)
        except (asyncio.CancelledError, KeyboardInterrupt):
            status, reason = "PAUSED", "interrupted"
            raise
        except Exception as exc:
            status, reason = "FAILED", f"execution_{type(exc).__name__}"
        finally:
            await self.browser.close()
            self.store.finish(
                self.rid, status, reason, self.client.total_tokens, self.client.reserved_tokens
            )
        return status, reason
