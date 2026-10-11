# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""An unrelated or ambiguous decision must never authorize a changed contract."""

import json
from contextlib import closing
from unittest.mock import AsyncMock

import pytest
from verboisy.api import arun
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.storage.changes import (
    current_requirement_events,
    decide_change,
    pending_change,
    propose_change,
)
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_change_decisions import NEW, OLD, request


def state(store):
    """Compare raw journal and frontier, including unchanged consumed budgets."""
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ["research_runs", "pages", "events", "records", "candidates", "snapshots"]
    }


DAMAGES = [
    "proposal_duplicate_key",
    "proposal_nested_duplicate",
    "proposal_nonfinite",
    "proposal_overflow",
    "proposal_json",
    "proposal_blank_goal",
    "proposal_blank_description",
    "proposal_blank_id",
    "proposal_baseline_format",
    "decision_duplicate_key",
    "decision_json",
    "decision_scalar",
    "decision_missing",
    "decision_unknown",
    "decision_wrong_type",
    "decision_wrong_id",
    "decision_wrong_baseline",
    "previous_goal",
    "previous_schema",
    "previous_task",
    "orphan",
    "repeated_decision",
    "overlapping_proposals",
    "reused_proposal_id",
    "historical_damage",
]


def corrupt_history(store, rid, damage):
    proposal = propose_change(store, rid, request())
    raw_proposal = proposal.model_dump_json(by_alias=True)
    if damage.startswith("proposal_"):
        if damage in {
            "proposal_blank_goal",
            "proposal_blank_description",
            "proposal_blank_id",
            "proposal_baseline_format",
        }:
            saved = proposal.model_dump(mode="json", by_alias=True)
            if damage == "proposal_blank_goal":
                saved["request"]["goal"] = " "
            elif damage == "proposal_blank_description":
                saved["request"]["description"] = " "
            elif damage == "proposal_blank_id":
                saved["proposal_id"] = ""
            else:
                saved["baseline_sha256"] = "not a digest"
            raw = json.dumps(saved)
        else:
            raw = {
                "proposal_duplicate_key": raw_proposal[:-1] + ',"version":1}',
                "proposal_nested_duplicate": raw_proposal.replace(
                    '"description":', '"description":"duplicate", "description":', 1
                ),
                "proposal_nonfinite": raw_proposal.replace('"schema":{', '"schema":{"bad":NaN,', 1),
                "proposal_overflow": raw_proposal.replace(
                    '"schema":{', '"schema":{"bad":1e999,', 1
                ),
                "proposal_json": "not JSON",
            }[damage]
        store.db.execute(
            "UPDATE events SET payload=? WHERE run_id=? AND kind='change_proposed'", (raw, rid)
        )
        store.db.commit()
        return
    if damage == "overlapping_proposals":
        other = proposal.model_copy(update={"proposal_id": "another"})
        store.event(rid, "change_proposed", other.model_dump(mode="json", by_alias=True))
        return
    decide_change(store, rid, accept=False)
    decision = store.events(rid, "change_decided")[-1]["payload"]
    if damage == "repeated_decision":
        store.event(rid, "change_decided", decision)
        return
    if damage == "reused_proposal_id":
        store.event(rid, "change_proposed", proposal.model_dump(mode="json", by_alias=True))
        return
    if damage == "orphan":
        store.db.execute("DELETE FROM events WHERE run_id=? AND kind='change_proposed'", (rid,))
        store.db.commit()
        return
    if damage == "historical_damage":
        propose_change(store, rid, request(goal="Another search"))
        decision["proposal_id"] = "unrelated historical proposal"
    elif damage == "decision_wrong_id":
        decision["proposal_id"] = "unrelated"
    elif damage == "decision_wrong_baseline":
        decision["baseline_sha256"] = "0" * 64
    elif damage.startswith("previous_"):
        key = damage.removeprefix("previous_")
        decision["previous_requirements"][key] = {
            "goal": "Other goal",
            "schema": NEW,
            "task": TaskSpec(target_records=99).model_dump(),
        }[key]
    elif damage == "decision_missing":
        del decision["previous_requirements"]
    elif damage == "decision_unknown":
        decision["decision"] = "maybe"
    elif damage == "decision_wrong_type":
        decision["decision"] = True
    raw = json.dumps(decision)
    if damage == "decision_duplicate_key":
        raw = raw[:-1] + ',"decision":"declined"}'
    elif damage == "decision_json":
        raw = "not JSON"
    elif damage == "decision_scalar":
        raw = "null"
    store.db.execute(
        "UPDATE events SET payload=? WHERE run_id=? AND kind='change_decided'", (raw, rid)
    )
    store.db.commit()


def prepare(path, damage):
    with closing(ResearchStore(path)) as store:
        rid = store.create("Breed weights", OLD, TaskSpec(), None)
        store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
        store.queue(rid, "https://example.test/", 0, None)
        store.event(rid, "field_semantics_plan", {"original": True})
        corrupt_history(store, rid, damage)
        return rid, state(store)


@pytest.mark.parametrize("damage", DAMAGES)
@pytest.mark.parametrize("operation", ["inspect", "accept", "decline", "planning"])
def test_invalid_history_rejected_without_mutation_after_reopen(tmp_path, damage, operation):
    path = tmp_path / "changes.db"
    rid, before = prepare(path, damage)
    with closing(ResearchStore(path, read_only=operation in {"inspect", "planning"})) as reader:
        with pytest.raises(VerboisyError):
            if operation == "inspect":
                pending_change(reader, rid)
            elif operation == "planning":
                current_requirement_events(reader, rid, "field_semantics_plan")
            else:
                decide_change(reader, rid, accept=operation == "accept")
        assert state(reader) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["resume", "okresume"])
@pytest.mark.parametrize(
    "damage", ["decision_wrong_id", "decision_scalar", "proposal_duplicate_key"]
)
async def test_resume_rejects_bad_decision_before_research(tmp_path, monkeypatch, flag, damage):
    path = tmp_path / "resume.db"
    rid, before = prepare(path, damage)
    execution = AsyncMock(side_effect=AssertionError("Research must not start"))
    monkeypatch.setattr(ResearchRunner, "run", execution)
    with pytest.raises(VerboisyError):
        await arun(**{flag: rid}, config=Settings(_env_file=None, sqlite_db_path=str(path)))
    execution.assert_not_awaited()
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert state(reader) == before


@pytest.mark.parametrize("first_accept", [False, True])
@pytest.mark.parametrize("second_accept", [False, True])
@pytest.mark.parametrize("legacy_task", [False, True])
def test_valid_multiple_decisions_keep_history_and_clear_only_accepted_plans(
    tmp_path, first_accept, second_accept, legacy_task
):
    path = tmp_path / "valid.db"
    with closing(ResearchStore(path)) as store:
        rid = store.create("Breed weights", OLD, TaskSpec(), None)
        if legacy_task:
            # Older task JSON can omit optional defaults. Its original hash,
            # rather than a model dump with defaults, remains authoritative.
            store.db.execute("UPDATE research_runs SET task_json='{}' WHERE id=?", (rid,))
            store.db.commit()
        store.finish(rid, "PAUSED", "fixture", 17, 796)
        store.event(rid, "field_semantics_plan", {"generation": 0})
        first = propose_change(store, rid, request())
        decide_change(store, rid, accept=first_accept)
        store.event(rid, "field_semantics_plan", {"generation": 1})
        second = propose_change(store, rid, request(goal="Other goal"))
        assert second.proposal_id != first.proposal_id
        decide_change(store, rid, accept=second_accept)
        store.event(rid, "field_semantics_plan", {"generation": 2})
        expected = [2] if second_accept else ([1, 2] if first_accept else [0, 1, 2])
        before = state(store)
    with closing(ResearchStore(path, read_only=True)) as reader:
        assert pending_change(reader, rid) is None
        assert [
            event["payload"]["generation"]
            for event in current_requirement_events(reader, rid, "field_semantics_plan")
        ] == expected
        assert state(reader) == before
        assert (reader.load(rid)["tokens"], reader.load(rid)["reserved"]) == (17, 796)
