# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Collection stops at its row target; unresolved evidence remains a pause."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.core.run_outcome import page_limit_outcome
from verboisy.evidence.models import Candidate, PageProposal, Proof, Snapshot, Source
from verboisy.evidence.verify import verify
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


def arrange(monkeypatch, store, rid, task, *, target=1, metadata=False):
    config = Settings(
        _env_file=None,
        search_provider="disabled",
        action_delay_seconds=0,
        litellm_model="openai/test",
        litellm_api_key="fixture",
    )
    runner = ResearchRunner(store, rid, config)
    runner.task = task.model_copy(update={"target_records": target, "settle_ms": 0})
    runner.semantic_plan_ready = True
    runner.adaptive_frontier = False
    html = "bounded fixture with a following unrelated evidence chunk"
    record = {"name": "Alba", "population": 2, "revision": "first"}
    sources = [
        Source(id=key, kind="text", scope="entity", text=str(value))
        for key, value in record.items()
    ] + [Source(id="unit", kind="text", scope="entity", text="Population unit: persons.")]
    unrelated = Source(id="unrelated", kind="text", scope="other", text="Not the target")
    snapshot = Snapshot(
        id="new-snapshot",
        url="https://example.test/repair",
        fetched_at="2026-10-26T00:00:00Z",
        content_hash=hashlib.sha256(html.encode()).hexdigest(),
        truncated=False,
        sources=[*sources, unrelated],
    )
    candidate = Candidate(
        scope="entity",
        record=record,
        evidence={
            "/" + key: Proof(
                source=key, quote=str(value), transform="integer" if key == "population" else "text"
            )
            for key, value in record.items()
        },
    )
    assert verify(candidate, snapshot, SCHEMA, task) == []
    monkeypatch.setattr(
        "verboisy.core.research.capture_rendered_page",
        AsyncMock(return_value=(snapshot, snapshot.url, html, html)),
    )
    monkeypatch.setattr("verboisy.core.research.chunks", lambda *_args: [sources, [unrelated]])
    monkeypatch.setattr("verboisy.core.research.advance_page", AsyncMock(return_value=False))
    runner.browser = SimpleNamespace(
        start=AsyncMock(), close=AsyncMock(), navigate_to=AsyncMock(), get_page=AsyncMock()
    )
    runner.extractor.propose = AsyncMock(
        side_effect=[PageProposal(candidates=[candidate]), PageProposal(candidates=[])]
    )
    runner.extractor.check = AsyncMock(return_value=[])
    assessment = {"pointer": "/population"}
    if metadata:
        assessment["unit"] = {
            "label": "persons",
            "citation": {"source": "unit", "quote": "Population unit: persons."},
        }
    response = {"candidates": [{"candidate_index": 0, "assessments": [assessment]}]}
    runner.client.complete_json = AsyncMock(return_value=response)
    store.queue_repair(rid, snapshot.url, 0, None)
    return runner


@pytest.mark.parametrize("metadata", [False, True])
async def test_reaching_target_never_requests_unrelated_chunk(tmp_path, monkeypatch, metadata):
    with ledger(tmp_path) as (store, rid, task):
        runner = arrange(monkeypatch, store, rid, task, metadata=metadata)
        assert await runner.run(1) == (
            ("COMPLETED", "target_met") if metadata else ("PAUSED", "dataset_consistency_gaps")
        )
        runner.extractor.propose.assert_awaited_once()
        runner.extractor.check.assert_awaited_once()
        runner.client.complete_json.assert_awaited_once()
        payload = json.loads(runner.client.complete_json.await_args.args[1])
        assert payload["candidates"][0]["required_comparability"] == {"/population": ["unit"]}
        records = store.records(rid)
        assert len(records) == 1 and records[0]["id"]
        assert {k: v for k, v in records[0].items() if k != "id"} == {
            "name": "Alba",
            "population": 2,
            "revision": "first",
        }
        assert store.evidence(rid)[0]["candidate"]["record"]["population"] == 2
        gaps = store.events(rid, "dataset_consistency_gap")
        if metadata:
            assert gaps == []
        else:
            assert gaps[-1]["payload"]["gaps"] == ["/population:unknown_unit"]
            assert gaps[-1]["payload"]["repairs"][0]["target_mode"] == "unit"
            assert store.load(rid)["reason"] == "dataset_consistency_gaps"
        assert not store.events(rid, "dataset_repair_discovery")


@pytest.mark.parametrize("target", [None, 2])
async def test_incomplete_collection_keeps_inspecting_chunks(tmp_path, monkeypatch, target):
    with ledger(tmp_path) as (store, rid, task):
        runner = arrange(monkeypatch, store, rid, task, target=target)
        assert await runner.run(1) == ("PAUSED", "page_budget")
        assert runner.extractor.propose.await_count == 2
        assert not store.events(rid, "dataset_consistency_gap")


async def test_page_entered_for_repair_can_inspect_later_chunks(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "widgets")
        runner = arrange(monkeypatch, store, rid, task)
        runner.extractor.propose = AsyncMock(
            side_effect=[PageProposal(candidates=[]), PageProposal(candidates=[])]
        )
        work = store.next_page(rid)
        assert work is not None
        await runner.process(work)
        assert runner.extractor.propose.await_count == 2
        assert not runner.target_met()
        runner.client.complete_json.assert_not_awaited()


async def test_repair_workflow_is_reached_when_steps_remain(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        runner = arrange(monkeypatch, store, rid, task)
        runner.discover_dataset_repair_source = AsyncMock(return_value=False)
        assert await runner.run(2) == ("PAUSED", "dataset_consistency_gaps")
        runner.discover_dataset_repair_source.assert_awaited_once()
        assert runner.discover_dataset_repair_source.await_args.args[0][0]["target_mode"] == "unit"
        runner.extractor.propose.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("COMPLETED", "target_met"),
        ("FAILED", "source_failures"),
        ("EXHAUSTED", "observed_scope_exhausted"),
        ("PAUSED", "coverage_or_identity_gaps"),
        ("PAUSED", "dataset_consistency_gaps"),
    ],
)
def test_page_limit_retains_selected_outcome_without_rechecking(monkeypatch, status, reason):
    check = MagicMock(side_effect=AssertionError("An existing outcome must not be reassessed"))
    monkeypatch.setattr("verboisy.core.run_outcome.dataset_consistency_outcome", check)
    runner = ResearchRunner.__new__(ResearchRunner)
    assert page_limit_outcome(runner, status, reason) == (status, reason)
    check.assert_not_called()


async def test_page_limit_journal_failure_still_saves_checkpoint(tmp_path, monkeypatch):
    with ledger(tmp_path) as (store, rid, task):
        runner = arrange(monkeypatch, store, rid, task)
        journal = store.event

        def fail_consistency_event(run_id, event_type, payload):
            if event_type == "dataset_consistency_gap":
                raise OSError("Diagnostic write failed")
            return journal(run_id, event_type, payload)

        monkeypatch.setattr(store, "event", fail_consistency_event)
        assert await runner.run(1) == ("FAILED", "execution_OSError")
        state = store.load(rid)
        assert (state["status"], state["reason"]) == ("FAILED", "execution_OSError")
        assert len(store.records(rid)) == 1
        runner.browser.close.assert_awaited_once()
