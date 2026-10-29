# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Persisted breadth-first traversal. A model cannot declare a run complete."""

import asyncio
import fnmatch
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError

from verboisy.browser.context import BrowserManager
from verboisy.core.assessment_journal import journal_candidate_assessments
from verboisy.core.candidate_admission import admit_reviewed_candidate
from verboisy.core.dataset_consistency import (
    accepted_comparability_observations,
    accepted_consistency_gaps,
    accepted_consistency_repairs,
)
from verboisy.core.evidence_comparison import compare_evidence, metadata_evidence_improves
from verboisy.core.fitness import (
    ClaimFitness,
    build_field_semantics,
)
from verboisy.core.frontier_discovery import discover_frontier, frontier_batch_size
from verboisy.core.page_batches import prepare_page_batches
from verboisy.core.page_capture import CAPTURE_PAGE as CAPTURE_PAGE
from verboisy.core.page_capture import capture_rendered_page
from verboisy.core.page_pagination import advance_page
from verboisy.core.planner import (
    build_research_plan,
    infer_temporal_intent,
    source_productivity_score,
)
from verboisy.core.proposal_review import review_page_proposal
from verboisy.core.repair_discovery import discover_repair_source
from verboisy.core.run_outcome import exhausted_frontier_outcome, page_limit_outcome
from verboisy.core.search import web_search
from verboisy.core.semantic_plan_journal import journal_field_semantics
from verboisy.core.semantic_planner import (
    classify_field_semantics,
    semantic_plan_event,
    semantic_plan_from_event,
)
from verboisy.core.source_assessment import (
    GroundedClaimAssessment,
    SourceAssessmentBatchResponse,
    assess_source_batch,
    ground_source_assessment_batch,
)
from verboisy.core.source_batches import rank_source_batches, window_source_batches
from verboisy.core.source_productivity import (
    journal_source_productivity,
    productivity_scores,
    replay_source_productivity,
)
from verboisy.core.unit_normalization import journal_unit_normalizations
from verboisy.evidence.models import Candidate, Snapshot, Source, TaskSpec
from verboisy.evidence.snapshot import canonical_url, chunks, snapshot
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.extractor.range_changes import (
    ProposedChangesPauseError,
    candidate_range_conflicts,
    offer_range_change,
)
from verboisy.extractor.research_changes import offer_research_change
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.llm.client import LLMClient, ModelRole
from verboisy.llm.providers import resolve_provider
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import (
    BudgetExceededError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    NavigationError,
    SearchBudgetExceededError,
)


class ResearchRunner:
    # Created only after an invalid semantic-plan gap is durably journaled.
    semantic_plan_failed: bool

    def __init__(self, store: ResearchStore, rid: str, config: Settings):
        self.store, self.rid, self.config = store, rid, config
        row = store.load(rid)
        self.task = TaskSpec.model_validate_json(row["task_json"])
        self.schema = json.loads(row["schema_json"])
        self.goal = row["goal"]

        from verboisy.storage.changes import current_requirement_events

        semantic_events = current_requirement_events(store, rid, "field_semantics_plan")

        if semantic_events:
            (
                self.current_year,
                self.temporal_intent,
                self.field_semantics,
            ) = semantic_plan_from_event(
                semantic_events[-1]["payload"],
                schema=self.schema,
            )
            self.semantic_plan_ready = True
        else:
            self.current_year = datetime.now(UTC).year
            self.temporal_intent = infer_temporal_intent(
                self.goal,
                current_year=self.current_year,
            )
            self.field_semantics = build_field_semantics(self.schema)
            self.semantic_plan_ready = False

        self.plan = build_research_plan(
            self.schema,
            self.task.target_records,
        )
        self.adaptive_frontier = self.plan.task_shape == "bounded_list"

        self.source_productivity = replay_source_productivity(
            current_requirement_events(store, rid, "source_productivity")
        )
        self.client = LLMClient(config=config)
        self.client.total_tokens, self.client.reserved_tokens = row["tokens"], row["reserved"]
        self.client.search_requests = store.search_attempt_count(rid)
        self.client.on_usage = self.account
        self.client.on_escalation = self.record_model_escalation
        self.extractor = EvidenceExtractor(
            self.client,
            self.schema,
            self.task,
            self.goal,
            temporal_intent=self.temporal_intent,
            current_year=self.current_year,
            field_semantics=self.field_semantics,
        )
        self.browser = BrowserManager(config=config)
        self.hosts = {h.lower().rstrip(".") for h in self.task.allowed_hosts}
        self.avoided_hosts = {h.lower().rstrip(".") for h in self.task.avoided_hosts}
        self.browser.navigation_scope = self.in_scope

    def record_model_escalation(
        self,
        payload: dict[str, str],
    ) -> None:
        """Persist one stronger-model escalation."""
        self.store.event(
            self.rid,
            "model_escalation",
            payload,
        )

    def model_execution_available(self, role: ModelRole) -> bool:
        """Resolve role availability; configuration authorizes an attempt."""
        config = getattr(self, "config", None)
        client = getattr(self, "client", None)
        if config is None or client is None:
            return False
        model = str(
            client.model_for(role)
            if isinstance(client, LLMClient)
            else getattr(client, "model", "")
        )
        if not isinstance(config, Settings):
            if getattr(config, "litellm_api_key", None) or getattr(
                config, "litellm_api_base", None
            ):
                return True
            if model.startswith(("anthropic/", "claude-")):
                return getattr(config, "anthropic_api_key", None) is not None
            if model.startswith(("openai/", "gpt-", "o1", "o3", "o4")):
                return getattr(config, "openai_api_key", None) is not None
            return True
        resolved = resolve_provider(config, model)
        if resolved.prefix is not None or resolved.api_key is not None or resolved.api_base:
            return True
        # Unprofiled first-party roles preserve the deterministic no-provider path.
        return not model.startswith(("anthropic/", "claude-", "openai/", "gpt-", "o1", "o3", "o4"))

    def semantic_planning_available(self) -> bool:
        """Compatibility view of semantic-plan role availability."""
        return self.model_execution_available("semantic_plan")

    async def ensure_field_semantics(self) -> None:
        """Classify and persist field semantics through the existing journal workflow."""
        await journal_field_semantics(self, classify_field_semantics, semantic_plan_event)

    def account(self) -> None:
        self.store.finish(
            self.rid, "RUNNING", "running", self.client.total_tokens, self.client.reserved_tokens
        )

    def in_scope(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        host = str(parsed.hostname).lower().rstrip(".")
        if any(host == blocked or host.endswith("." + blocked) for blocked in self.avoided_hosts):
            return False
        host_allowed = not self.hosts or any(
            host == allowed or host.endswith("." + allowed) for allowed in self.hosts
        )
        return (
            host_allowed
            and (
                not self.task.include_paths
                or any(fnmatch.fnmatchcase(path, p) for p in self.task.include_paths)
            )
            and not any(fnmatch.fnmatchcase(path, p) for p in self.task.exclude_paths)
        )

    def dataset_comparability_observations(self) -> tuple[dict[str, object], ...]:
        """Return grounded metadata attached to accepted rows."""
        return accepted_comparability_observations(
            self.store, getattr(self, "rid", ""), getattr(self, "field_semantics", {})
        )

    def ensure_unit_normalizations(self) -> int:
        """Persist safe deterministic scale normalizations."""
        return journal_unit_normalizations(
            self.store,
            getattr(self, "rid", ""),
            getattr(self, "field_semantics", {}),
            self.dataset_comparability_observations,
        )

    def dataset_consistency_gaps(self) -> tuple[str, ...]:
        """Return deterministic gaps across accepted rows."""
        return accepted_consistency_gaps(
            self.store,
            getattr(self, "rid", ""),
            getattr(self, "field_semantics", {}),
            self.dataset_comparability_observations,
        )

    def dataset_consistency_repairs(self) -> tuple[dict[str, object], ...]:
        """Return row-scoped deterministic repair needs."""
        return accepted_consistency_repairs(
            self.store,
            getattr(self, "rid", ""),
            getattr(self, "field_semantics", {}),
            getattr(self, "temporal_intent", None),
            bool(getattr(getattr(self, "task", None), "dataset_sources", ())),
            self.dataset_comparability_observations,
        )

    def dataset_repair_discovery_available(
        self,
    ) -> bool:
        """Return whether targeted repair discovery is durable."""

        if not getattr(
            self.task,
            "identity_fields",
            (),
        ):
            return False

        return all(
            callable(
                getattr(
                    self.store,
                    name,
                    None,
                )
            )
            for name in (
                "records",
                "evidence",
                "events",
                "event",
                "queue",
            )
        )

    def target_record_count_met(
        self,
    ) -> bool:
        """Return whether the requested row count already exists."""

        target = getattr(
            self.task,
            "target_records",
            None,
        )
        records_method = getattr(
            self.store,
            "records",
            None,
        )

        if not isinstance(target, int) or not callable(records_method):
            return False

        return len(records_method(self.rid)) >= target

    async def discover_dataset_repair_source(
        self,
        repairs: tuple[dict[str, object], ...],
    ) -> bool:
        """Discover at most one durable targeted repair source."""
        identity_fields = tuple(getattr(self.task, "identity_fields", ()))
        if not identity_fields:
            return False
        attempts: set[str] = getattr(self, "_repair_discovery_attempts", set())
        self._repair_discovery_attempts = attempts
        return await discover_repair_source(
            self.store,
            self.rid,
            lambda: self.client,
            lambda: self.config,
            identity_fields,
            repairs,
            attempts,
            self.in_scope,
            web_search,
        )

    def target_met(self) -> bool:
        rows = self.store.records(self.rid)

        if (
            self.store.summary(self.rid)["identity_conflicts"]
            or self.task.target_records is None
            or len(rows) < self.task.target_records
        ):
            return False

        self.ensure_unit_normalizations()
        if self.dataset_consistency_gaps():
            return False

        # Normalization may have persisted deterministic events.
        # Validate the effective view used by exports and resumed runs.
        rows = self.store.records(self.rid)

        schema_rows = [{key: value for key, value in row.items() if key != "id"} for row in rows]

        return self.schema["type"] != "array" or bool(
            SchemaBuilder.validator(self.schema).is_valid(schema_rows)
        )

    def source_scores(self) -> dict[str, float]:
        """Return current run-level source yield estimates."""
        return productivity_scores(self.source_productivity, source_productivity_score)

    def record_source_productivity(
        self,
        url: str,
        *,
        accepted: int,
        rejected: int,
        duplicates: int,
    ) -> None:
        """Publish marginal dataset yield only after its durable event succeeds."""
        journal_source_productivity(
            self,
            url,
            accepted=accepted,
            rejected=rejected,
            duplicates=duplicates,
            score=source_productivity_score,
        )

    def window_batches(self, batches: list[list[Source]]) -> list[list[Source]]:
        """Split only genuinely large batches into target-aware entity windows."""
        # Resolve ledger counts and plan scoring only when the algorithm needs
        # them, preserving the no-target path and its borrowed batch objects.
        return window_source_batches(
            batches,
            getattr(self.task, "target_records", None),
            lambda: len(self.store.records(self.rid)),
            lambda text, count: self.plan.evidence_score(text, source_count=count),
        )

    def rank_batches(self, batches: list[list[Source]]) -> list[list[Source]]:
        """Put likely high-value evidence first without dropping anything."""
        return rank_source_batches(
            batches,
            lambda text, count: self.plan.evidence_score(text, source_count=count),
        )

    async def source_assess_candidates(
        self,
        page: Snapshot,
        candidates: list[Candidate],
    ) -> list[dict[str, GroundedClaimAssessment]]:
        """Assess verified candidates without affecting acceptance."""

        if not candidates:
            return []

        events = getattr(
            self,
            "_source_assessment_events",
            None,
        )

        if events is None:
            from verboisy.storage.changes import current_requirement_events

            events = current_requirement_events(
                self.store,
                self.rid,
                "source_assessment_cache",
            )
            self._source_assessment_events = events

        from verboisy.core.source_assessment import (
            cached_source_assessment,
            source_assessment_cache_key,
        )

        # Persisted cache hits remain usable when provider credentials are absent.
        semantics = getattr(self, "field_semantics", None)
        if cached_source_assessment(
            events, source_assessment_cache_key(page, candidates, field_semantics=semantics)
        ) is None and not self.model_execution_available("source_assessment"):
            return []

        async def request() -> SourceAssessmentBatchResponse:
            # Cache hits must not resolve a client, goal or model request budget.
            return await assess_source_batch(
                self.client,
                goal=self.goal,
                page=page,
                candidates=candidates,
                field_semantics=semantics,
            )

        return await journal_candidate_assessments(
            page,
            candidates,
            events,
            request,
            lambda kind, payload: self.store.event(self.rid, kind, payload),
            lambda rows, snapshot, response: ground_source_assessment_batch(
                rows, snapshot, response
            ),
            lambda: tuple(getattr(getattr(self, "task", None), "identity_fields", ())),
            field_semantics=semantics,
        )

    def compare_candidate_evidence(
        self,
        previous: Candidate,
        previous_snapshot_id: str | None,
        candidate: Candidate,
        current_snapshot_id: str,
    ) -> tuple[Any, str]:
        """Compare candidates using persisted source fitness when available."""
        return compare_evidence(
            self.store,
            getattr(self, "rid", ""),
            self.field_semantics,
            previous,
            previous_snapshot_id,
            candidate,
            current_snapshot_id,
            self.unit_evidence_improves,
        )

    def unit_evidence_improves(
        self,
        old: Candidate,
        old_snapshot_id: str,
        new: Candidate,
        new_snapshot_id: str,
        events: list[dict[str, object]],
        old_fitness: dict[str, ClaimFitness],
        new_fitness: dict[str, ClaimFitness],
        *,
        metadata_kind: str = "unit",
    ) -> bool:
        """Refresh equal values for missing metadata without losing prior evidence."""
        return metadata_evidence_improves(
            self.store,
            getattr(self, "rid", ""),
            getattr(self, "field_semantics", {}),
            old,
            old_snapshot_id,
            new,
            new_snapshot_id,
            events,
            old_fitness,
            new_fitness,
            metadata_kind=metadata_kind,
        )

    def frontier_batch_size(self) -> int:
        """Return the existing bounded frontier expansion budget."""
        return frontier_batch_size(self)

    def discover(
        self,
        page: Snapshot,
        depth: int,
        priorities: list[str],
        *,
        productive: bool = True,
    ) -> None:
        """Queue scoped links through the existing frontier policy."""
        discover_frontier(self, page, depth, priorities, productive=productive)

    async def process(self, work: dict[str, Any]) -> None:
        if not self.in_scope(work["url"]):
            self.store.mark_page(work["id"], "blocked", "scope_limit")
            return
        await self.browser.navigate_to(work["url"])
        page = await self.browser.get_page()
        seen: set[str] = set()
        interaction = 0
        page_batches = 0
        page_accepted = 0
        page_rejected = 0
        page_duplicates = 0
        collecting_rows = not self.target_record_count_met()

        while True:
            captured, url, html, visible_html = await capture_rendered_page(
                self, page, canonical_url, snapshot, CAPTURE_PAGE
            )
            # Compare evidence, not volatile resource attributes or timestamps.
            signature = json.dumps([s.model_dump() for s in captured.sources], sort_keys=True)
            if signature in seen:
                break
            seen.add(signature)
            self.store.snapshot(self.rid, work["id"], captured, html, visible_html)
            priorities: list[str] = []
            productive = False

            batches = await prepare_page_batches(self, captured, chunks)

            for batch in batches:
                page_batches += 1

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
                checked_candidates = await review_page_proposal(
                    self,
                    captured,
                    supplied,
                    proposal,
                    offer_range_change,
                    candidate_range_conflicts,
                    offer_research_change,
                )

                for candidate, errors in checked_candidates:
                    outcome = admit_reviewed_candidate(self, captured, supplied, candidate, errors)

                    if outcome == "accepted":
                        productive = True
                        page_accepted += 1
                    elif outcome == "rejected":
                        page_rejected += 1
                    else:
                        page_duplicates += 1

                    if self.target_met():
                        self.record_source_productivity(
                            work["url"],
                            accepted=page_accepted,
                            rejected=page_rejected,
                            duplicates=page_duplicates,
                        )
                        self.store.mark_page(
                            work["id"],
                            "done",
                        )
                        return

                # Hand a newly filled dataset back to bounded repair discovery.
                # Pages entered for repair may still inspect all their chunks.
                if (
                    collecting_rows
                    and self.target_record_count_met()
                    and self.dataset_consistency_gaps()
                ):
                    self.record_source_productivity(
                        work["url"],
                        accepted=page_accepted,
                        rejected=page_rejected,
                        duplicates=page_duplicates,
                    )
                    self.discover(captured, work["depth"], priorities, productive=productive)
                    self.store.mark_page(work["id"], "done", "dataset_repair_required")
                    return

                if self.adaptive_frontier and self.plan.should_stop_unproductive_page(
                    batches_seen=page_batches,
                    accepted=page_accepted,
                    rejected=page_rejected,
                ):
                    self.record_source_productivity(
                        work["url"],
                        accepted=page_accepted,
                        rejected=page_rejected,
                        duplicates=page_duplicates,
                    )

                    self.store.event(
                        self.rid,
                        "adaptive_probe_stop",
                        {
                            "page": captured.id,
                            "url": captured.url,
                            "batches_seen": page_batches,
                            "accepted": page_accepted,
                            "rejected": page_rejected,
                            "probe_batches": self.plan.probe_batches,
                            "rejection_cutoff": self.plan.rejection_cutoff,
                        },
                    )

                    self.discover(
                        captured,
                        work["depth"],
                        priorities,
                        productive=False,
                    )

                    self.store.mark_page(
                        work["id"],
                        "done",
                        "adaptive_probe_limit",
                    )
                    return

            self.discover(
                captured,
                work["depth"],
                priorities,
                productive=productive,
            )
            if not await advance_page(self, page, url, interaction):
                break
            interaction += 1
        self.record_source_productivity(
            work["url"],
            accepted=page_accepted,
            rejected=page_rejected,
            duplicates=page_duplicates,
        )
        self.store.mark_page(work["id"], "done")

    async def run(self, max_steps: int) -> tuple[str, str]:
        self.store.recover(self.rid)

        if self.adaptive_frontier:
            rebalance = self.store.rebalance_frontier(
                self.rid,
                self.frontier_batch_size(),
            )
            self.store.event(
                self.rid,
                "frontier_rebalance",
                rebalance,
            )

        status, reason = "PAUSED", "page_budget"
        try:
            async with asyncio.timeout(self.config.run_timeout_seconds):
                await self.browser.start()
                for _ in range(max_steps):
                    if self.target_met():
                        status, reason = "COMPLETED", "target_met"
                        break

                    if self.dataset_repair_discovery_available() and self.target_record_count_met():
                        repairs = self.dataset_consistency_repairs()

                        if repairs:
                            await self.discover_dataset_repair_source(repairs)

                    summary = self.store.summary(self.rid)
                    if (
                        sum(summary["pages"].get(s, 0) for s in ("done", "blocked"))
                        >= self.task.max_pages
                    ):
                        break
                    work = self.store.next_page(
                        self.rid,
                        self.source_scores(),
                    )
                    if work is None:
                        status, reason = exhausted_frontier_outcome(self, summary)

                        break
                    if work["depth"] > self.task.max_depth:
                        self.store.mark_page(work["id"], "blocked", "depth_limit")
                        continue
                    try:
                        await self.process(work)
                    except (NavigationError, PlaywrightError) as exc:
                        failure_reason = (
                            "navigation_failed"
                            if isinstance(exc, NavigationError)
                            else "browser_error"
                        )
                        self.store.mark_page(
                            work["id"],
                            "failed",
                            failure_reason,
                        )
                        self.store.event(
                            self.rid,
                            "page_failure",
                            {
                                "page_id": work["id"],
                                "reason": failure_reason,
                                "error_type": type(exc).__name__,
                            },
                        )
                    if self.target_met():
                        status, reason = "COMPLETED", "target_met"
                        break
                    await asyncio.sleep(self.config.action_delay_seconds)
                status, reason = page_limit_outcome(self, status, reason)
        except ProposedChangesPauseError:
            reason = "proposed_changes"
        except SearchBudgetExceededError:
            reason = "search_request_budget"
        except BudgetExceededError:
            reason = "model_request_budget"
        except TimeoutError:
            reason = "run_timeout"
        except LLMRateLimitError:
            status, reason = "PAUSED", "provider_rate_limit"
        except LLMError as exc:
            status, reason = "FAILED", str(exc)
        except (asyncio.CancelledError, KeyboardInterrupt):
            status, reason = "PAUSED", "interrupted"
            raise
        except Exception as exc:
            status, reason = "FAILED", f"execution_{type(exc).__name__}"
        finally:
            try:
                await self.browser.close()
            finally:
                # Browser cleanup can itself be cancelled. Persist the checkpoint
                # anyway so claimed pages remain resumable and usage is retained.
                self.store.recover(self.rid)
                self.store.finish(
                    self.rid, status, reason, self.client.total_tokens, self.client.reserved_tokens
                )
        return status, reason
