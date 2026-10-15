# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Availability follows each resolved role profile without paid authentication probes."""

from verboisy.core.research import ResearchRunner
from verboisy.llm.client import LLMClient
from verboisy.utils.config import Settings


def test_role_profiles_enable_only_matching_roles():
    config = Settings(
        _env_file=None,
        semantic_plan_model="openai/semantic",
        source_assessment_model="openai/other",
        llm_provider_profiles={"openai/semantic": {"api_base": "http://localhost:4000"}},
    )
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.config = config
    runner.client = LLMClient(config=config)
    assert runner.model_execution_available("semantic_plan") is True
    assert runner.model_execution_available("source_assessment") is False
    assert runner.semantic_planning_available() is True


async def test_unavailable_assessment_does_not_call_model():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from verboisy.evidence.models import Candidate
    from verboisy.evidence.snapshot import snapshot

    runner = ResearchRunner.__new__(ResearchRunner)
    runner.config = Settings(_env_file=None)
    runner.client = LLMClient(config=runner.config)
    runner.store = SimpleNamespace(event=Mock(), events=Mock(return_value=[]))
    runner.rid = "run"
    runner.task = SimpleNamespace(identity_fields=[])
    runner._source_assessment_events = []
    rows = await runner.source_assess_candidates(
        snapshot("<p>A</p>", "https://example.test/"),
        [Candidate(scope="page", record={"name": "A"}, evidence={})],
    )
    assert rows == []
    runner.store.event.assert_not_called()


async def test_empty_assessment_has_no_provider_or_ledger_dependency():
    from verboisy.evidence.snapshot import snapshot

    runner = ResearchRunner.__new__(ResearchRunner)
    assert (
        await runner.source_assess_candidates(snapshot("<p>A</p>", "https://example.test/"), [])
        == []
    )
