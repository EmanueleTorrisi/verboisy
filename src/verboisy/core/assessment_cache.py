# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Optional cross-run assessment reuse; fresh captures and grounding stay required."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Callable
from typing import Any

from verboisy.cache import CacheError, ProjectCache
from verboisy.cache_policy import CachePolicy
from verboisy.core.source_assessment import (
    SOURCE_ASSESSMENT_CACHE_VERSION,
    SOURCE_ASSESSMENT_PROMPT,
    SourceAssessmentBatchResponse,
    ground_source_assessment_batch,
    source_assessment_cache_key,
)
from verboisy.evidence.models import Candidate, Snapshot
from verboisy.llm.client import LLMClient, ModelRole
from verboisy.llm.providers import resolve_provider


class AssessmentCache:
    def __init__(
        self, runner: Any, page: Snapshot, candidates: list[Candidate], policy: CachePolicy
    ):
        self.policy, self.page, self.candidates = policy, page, candidates
        self.journal: Callable[[str, dict[str, Any]], Any] = (
            lambda kind, payload: runner.store.event(runner.rid, kind, payload)
        )
        config = runner.config
        client = runner.client
        if not isinstance(client, LLMClient):
            raise CacheError("Persistent assessment caching requires the configured model client")
        routes = []
        roles: tuple[ModelRole, ...] = ("source_assessment", "escalation")
        for role in roles:
            model = client.model_for(role)
            provider = resolve_provider(config, model)
            # Credentials are never read, serialized or hashed. The project scope
            # is explicit; the current source is acquired under current permissions.
            routes.append(
                {
                    "model": model,
                    "profile": provider.prefix,
                    "endpoint": provider.api_base,
                    "response_mode": provider.response_mode,
                    "token_parameter": provider.token_limit_parameter,
                    "max_tokens": provider.max_tokens,
                    "temperature": config.temperature if provider.send_temperature else None,
                }
            )
        contract = {
            "version": 1,
            "scope": policy.scope,
            "assessment_version": SOURCE_ASSESSMENT_CACHE_VERSION,
            "prompt": SOURCE_ASSESSMENT_PROMPT,
            "sdk": importlib.metadata.version("litellm"),
            "goal": runner.goal,
            "schema": runner.schema,
            "task": runner.task.model_dump(mode="json"),
            "routes": routes,
            "inputs": source_assessment_cache_key(
                page, candidates, field_semantics=getattr(runner, "field_semantics", None)
            ),
        }
        raw = json.dumps(
            contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self.key = hashlib.sha256(raw).hexdigest()

    def note(self, operation: str, outcome: str, **details: Any) -> None:
        self.journal(
            "persistent_cache",
            {
                "version": 1,
                "stage": "source_assessment",
                "operation": operation,
                "outcome": outcome,
                **details,
            },
        )

    def load(self) -> SourceAssessmentBatchResponse | None:
        try:
            with ProjectCache(self.policy) as cache:
                found = cache.get(self.key)
        except CacheError:
            self.note("lookup", "unavailable")
            return None
        if found.payload is None:
            self.note("lookup", found.state)
            return None
        try:
            response = SourceAssessmentBatchResponse.model_validate(found.payload)
            grounded = ground_source_assessment_batch(self.candidates, self.page, response)
            if not all(claim.grounded for row in grounded for claim in row.values()):
                raise ValueError("Cached assessment is not grounded in this capture")
        except (TypeError, ValueError):
            self.note("lookup", "rejected")
            return None
        self.note("lookup", "hit", age_seconds=found.age_seconds)
        return response

    def store(self, response: SourceAssessmentBatchResponse) -> None:
        try:
            with ProjectCache(self.policy) as cache:
                written = cache.put(self.key, response.model_dump(mode="json"))
        except CacheError:
            self.note("store", "unavailable")
        else:
            self.note("store", "stored" if written else "oversized")
