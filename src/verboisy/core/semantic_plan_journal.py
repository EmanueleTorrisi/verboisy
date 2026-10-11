# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Persist a semantic plan before publishing it to the current extraction workflow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from verboisy.core.fitness import FieldSemantics
from verboisy.utils.exceptions import LLMResponseError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


async def journal_field_semantics(
    runner: ResearchRunner,
    classify: Callable[..., Awaitable[dict[str, FieldSemantics]]],
    encode_plan: Callable[..., dict[str, Any]],
) -> None:
    """Classify and persist field semantics at most once per run."""

    if getattr(
        runner,
        "semantic_plan_ready",
        True,
    ):
        return

    if getattr(
        runner,
        "semantic_plan_failed",
        False,
    ):
        raise LLMResponseError("semantic planning already failed")

    unresolved = any(field.basis == "unresolved" for field in runner.field_semantics.values())

    if unresolved:
        # Preserve no-provider/test operation. The unresolved
        # deterministic baseline remains usable, but is not
        # persisted as a completed semantic plan so that a later
        # resume with credentials can enrich it.
        if not runner.semantic_planning_available():
            runner.semantic_plan_ready = True
            return

        semantics = await classify(
            runner.client,
            goal=runner.goal,
            schema=runner.schema,
            temporal_intent=runner.temporal_intent,
            current_year=runner.current_year,
        )
    else:
        semantics = runner.field_semantics

    runner.store.event(
        runner.rid,
        "field_semantics_plan",
        encode_plan(
            semantics,
            research_year=runner.current_year,
            temporal_intent=runner.temporal_intent,
        ),
    )

    # Readiness and extractor state follow a successful durable journal write.
    runner.field_semantics = semantics
    runner.semantic_plan_ready = True

    runner.extractor.field_semantics = semantics
    runner.extractor.temporal_intent = runner.temporal_intent
    runner.extractor.current_year = runner.current_year
