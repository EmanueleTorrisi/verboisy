# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cross-run reuse always preserves fresh-source grounding and journal ordering."""

from contextlib import closing
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.cache import ProjectCache
from verboisy.core.assessment_cache import AssessmentCache
from verboisy.core.research import ResearchRunner
from verboisy.core.source_assessment import SourceAssessmentBatchResponse
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings


@pytest.fixture
def assessment_world(tmp_path, monkeypatch):
    config = Settings(_env_file=None, cache_directory=tmp_path / "cache", cache_scope="team")
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    page = Snapshot(
        id="capture-one",
        url="https://example.test/item",
        fetched_at="2026-01-01T00:00:00Z",
        content_hash=sha256(b"Alpha").hexdigest(),
        truncated=False,
        sources=[Source(id="e0", kind="text", text="Alpha", scope="s0")],
    )
    rows = [
        Candidate(
            scope="s0",
            record={"name": "Alpha"},
            evidence={"/name": Proof(source="e0", quote="Alpha")},
        )
    ]
    response = SourceAssessmentBatchResponse.model_validate(
        {
            "candidates": [
                {
                    "candidate_index": 0,
                    "assessments": [
                        {
                            "pointer": "/name",
                            "authority": "general",
                            "directness": "primary",
                            "citations": [{"source": "e0", "quote": "Alpha"}],
                        }
                    ],
                }
            ]
        }
    )
    request = AsyncMock(return_value=response)
    monkeypatch.setattr("verboisy.core.research.assess_source_batch", request)
    with closing(ResearchStore(tmp_path / "research.db")) as store:

        def runner(chosen=config, available=True):
            rid = store.create("Find names", schema, TaskSpec(), None)
            result = ResearchRunner(store, rid, chosen)
            result.model_execution_available = lambda _role: available
            return result

        yield SimpleNamespace(
            config=config,
            page=page,
            rows=rows,
            response=response,
            request=request,
            store=store,
            runner=runner,
        )


async def test_separate_runs_reuse_without_credentials_or_model_reservations(assessment_world):
    w = assessment_world
    first = w.runner()
    initial = await first.source_assess_candidates(w.page, w.rows)
    second = w.runner(available=False)
    fresh = w.page.model_copy(update={"id": "fresh-capture", "fetched_at": "2026-01-01T00:01:00Z"})
    reused = await second.source_assess_candidates(fresh, w.rows)
    assert initial == reused and reused[0]["/name"].grounded
    assert w.request.await_count == 1
    assert second.client.reserved_tokens == 0
    kinds = [e["kind"] for e in w.store.events(second.rid)]
    assert kinds.index("source_assessment_cache") < kinds.index("source_fitness")
    assert any(
        e["payload"]["outcome"] == "hit"
        for e in w.store.events(second.rid)
        if e["kind"] == "persistent_cache"
    )


async def test_within_run_hit_does_not_refresh_persistent_expiry(assessment_world):
    w = assessment_world
    runner = w.runner()
    await runner.source_assess_candidates(w.page, w.rows)
    policy = w.config.cache_policy()
    cache_key = AssessmentCache(runner, w.page, w.rows, policy).key
    with ProjectCache(policy) as cache:
        before = (
            cache._db()
            .execute("SELECT created,expires FROM entries WHERE key=?", (cache_key,))
            .fetchone()
        )
    await runner.source_assess_candidates(w.page, w.rows)
    with ProjectCache(policy) as cache:
        assert (
            cache._db()
            .execute("SELECT created,expires FROM entries WHERE key=?", (cache_key,))
            .fetchone()
            == before
        )
    assert w.request.await_count == 1


@pytest.mark.parametrize(
    "change",
    [
        {"cache_scope": "other"},
        {"source_assessment_model": "gpt-other"},
        {"litellm_api_base": "http://localhost:9999/v1"},
        {"temperature": 0.5},
        {"llm_response_mode": "prompt"},
        {"llm_send_temperature": False},
        {"max_tokens": 128},
        {"escalation_model": "gpt-escalation"},
    ],
)
def test_request_contract_changes_invalidate_key(assessment_world, change):
    w = assessment_world
    first = w.runner()
    other = w.runner(w.config.model_copy(update=change))
    assert (
        AssessmentCache(first, w.page, w.rows, w.config.cache_policy()).key
        != AssessmentCache(other, w.page, w.rows, other.config.cache_policy()).key
    )


def test_goal_schema_task_prompt_and_source_changes_invalidate(assessment_world, monkeypatch):
    w = assessment_world
    runner = w.runner()
    policy = w.config.cache_policy()
    original = AssessmentCache(runner, w.page, w.rows, policy).key
    runner.goal = "Find different names"
    assert AssessmentCache(runner, w.page, w.rows, policy).key != original
    runner.goal = "Find names"
    runner.schema = {**runner.schema, "description": "new contract"}
    assert AssessmentCache(runner, w.page, w.rows, policy).key != original
    runner.schema.pop("description")
    runner.task = TaskSpec(include_paths=["/item"])
    assert AssessmentCache(runner, w.page, w.rows, policy).key != original
    runner.task = TaskSpec()
    changed = w.page.model_copy(update={"content_hash": sha256(b"changed").hexdigest()})
    assert AssessmentCache(runner, changed, w.rows, policy).key != original
    monkeypatch.setattr("verboisy.core.assessment_cache.SOURCE_ASSESSMENT_PROMPT", "Changed policy")
    assert AssessmentCache(runner, w.page, w.rows, policy).key != original


@pytest.mark.parametrize(
    "payload",
    [
        {"wrong": "shape"},
        {"candidates": [{"candidate_index": 999, "assessments": []}]},
        {
            "candidates": [
                {
                    "candidate_index": 0,
                    "assessments": [
                        {
                            "pointer": "/name",
                            "authority": "responsible",
                            "citations": [{"source": "e0", "quote": "Invented citation"}],
                        }
                    ],
                }
            ]
        },
    ],
)
async def test_invalid_cached_response_is_rejected_then_regular_budgeted_path_runs(
    assessment_world, payload
):
    w = assessment_world
    first = w.runner()
    await first.source_assess_candidates(w.page, w.rows)
    cache_key = AssessmentCache(first, w.page, w.rows, w.config.cache_policy()).key
    with ProjectCache(w.config.cache_policy()) as cache:
        cache.put(cache_key, payload)
    second = w.runner()
    result = await second.source_assess_candidates(w.page, w.rows)
    assert result[0]["/name"].grounded and w.request.await_count == 2
    assert any(
        e["payload"]["outcome"] == "rejected"
        for e in w.store.events(second.rid)
        if e["kind"] == "persistent_cache"
    )


async def test_unavailable_optional_cache_preserves_regular_research(assessment_world):
    w = assessment_world
    w.config.cache_directory.mkdir(mode=0o700)
    path = w.config.cache_policy().database
    path.write_bytes(b"Unrelated file")
    path.chmod(0o600)
    result = await w.runner().source_assess_candidates(w.page, w.rows)
    assert result[0]["/name"].grounded and w.request.await_count == 1
    assert path.read_bytes() == b"Unrelated file"


async def test_cache_hit_must_journal_before_becoming_current_run_state(
    assessment_world, monkeypatch
):
    w = assessment_world
    await w.runner().source_assess_candidates(w.page, w.rows)
    second = w.runner(available=False)
    original = w.store.event

    def fail(rid, kind, payload):
        if kind == "source_assessment_cache":
            raise OSError("synthetic full disk")
        return original(rid, kind, payload)

    monkeypatch.setattr(w.store, "event", fail)
    with pytest.raises(OSError):
        await second.source_assess_candidates(w.page, w.rows)
    assert second._source_assessment_events == [] and w.request.await_count == 1


async def test_failed_fresh_journal_cannot_populate_persistent_cache(assessment_world, monkeypatch):
    w = assessment_world
    runner = w.runner()
    original = w.store.event

    def fail(rid, kind, payload):
        if kind == "source_assessment_cache":
            raise OSError("synthetic full disk")
        return original(rid, kind, payload)

    monkeypatch.setattr(w.store, "event", fail)
    with pytest.raises(OSError):
        await runner.source_assess_candidates(w.page, w.rows)
    with ProjectCache(w.config.cache_policy()) as cache:
        assert cache.stats()["entries"] == 0


async def test_disabled_empty_or_custom_client_does_not_open_a_cache(assessment_world):
    w = assessment_world
    disabled = w.config.model_copy(update={"cache_directory": None})
    assert await w.runner(disabled).source_assess_candidates(w.page, w.rows)
    assert not w.config.cache_directory.exists()
    assert await w.runner().source_assess_candidates(w.page, []) == []
    custom = w.runner(available=False)
    custom.client = SimpleNamespace()
    assert await custom.source_assess_candidates(w.page, w.rows) == []
    assert not w.config.cache_directory.exists()


async def test_missing_grounding_is_not_persisted(assessment_world):
    w = assessment_world
    w.request.return_value = SourceAssessmentBatchResponse()
    result = await w.runner().source_assess_candidates(w.page, w.rows)
    assert not result[0]["/name"].grounded
    with ProjectCache(w.config.cache_policy()) as cache:
        assert cache.stats()["entries"] == 0


async def test_oversized_optional_response_is_not_stored(assessment_world):
    w = assessment_world
    runner = w.runner(w.config.model_copy(update={"cache_max_entry_bytes": 1}))
    assert await runner.source_assess_candidates(w.page, w.rows)
    assert any(
        e["payload"]["outcome"] == "oversized"
        for e in w.store.events(runner.rid)
        if e["kind"] == "persistent_cache"
    )
