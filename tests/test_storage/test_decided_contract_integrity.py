# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Closed decisions must agree with live requirements before further research."""

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

from tests.test_research.test_saved_range_resume_integrity import state
from tests.test_storage.test_change_decisions import OLD, request


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    rid = store.create("Breed weights", OLD, TaskSpec(seed_urls=["https://example.test/"]), None)
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    store.event(rid, "product_options", {"strings": False})
    yield path, store, rid
    store.close()


def damage_contract(store, rid, damage):
    original = store.load(rid)
    if damage == "goal":
        column, value = "goal", "Unrelated research goal"
    elif damage == "schema":
        schema = json.loads(original["schema_json"])
        schema["properties"]["extra"] = {"type": "string"}
        column, value = "schema_json", json.dumps(schema)
    else:
        task = json.loads(original["task_json"])
        key, value = {
            "target": ("target_records", 19),
            "identity": ("identity_fields", ["/weight"]),
            "csv": ("csv_mode", "spreadsheet"),
            "invalid_task": ("target_records", 0),
        }[damage]
        task[key] = value
        column, value = "task_json", json.dumps(task)
    store.db.execute(f"UPDATE research_runs SET {column}=? WHERE id=?", (value, rid))
    store.db.commit()


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("damage", ["goal", "schema", "target", "identity", "csv", "invalid_task"])
@pytest.mark.parametrize("operation", ["inspect", "planning", "proposal", "resume"])
async def test_closed_contract_damage_blocks_work_without_mutation(
    ledger, monkeypatch, accept, damage, operation
):
    path, store, rid = ledger
    propose_change(store, rid, request())
    decide_change(store, rid, accept=accept)
    damage_contract(store, rid, damage)
    before = state(store)
    run = AsyncMock(side_effect=AssertionError("Research must not start"))
    monkeypatch.setattr(ResearchRunner, "run", run)
    with pytest.raises(VerboisyError, match="Saved requirements differ from the last decision"):
        if operation == "inspect":
            pending_change(store, rid)
        elif operation == "planning":
            current_requirement_events(store, rid, "semantic_plan")
        elif operation == "proposal":
            propose_change(store, rid, request(goal="Another proposed goal"))
        else:
            store.close()
            await arun(
                resume=rid,
                config=Settings(
                    _env_file=None, sqlite_db_path=str(path), search_provider="disabled"
                ),
            )
    run.assert_not_called()
    with closing(ResearchStore(path, read_only=True)) as reopened:
        assert state(reopened) == before


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("style", ["format", "defaults", "seeds"])
def test_equivalent_task_and_discovered_seeds_remain_valid(ledger, accept, style):
    _, store, rid = ledger
    propose_change(store, rid, request())
    decide_change(store, rid, accept=accept)
    original = store.load(rid)
    task = json.loads(original["task_json"])
    if style == "defaults":
        task = TaskSpec.model_validate(task).model_dump(exclude_defaults=True)
    elif style == "seeds":
        task["seed_urls"] = ["https://example.test/discovered"]
    store.db.execute(
        "UPDATE research_runs SET task_json=?,schema_json=? WHERE id=?",
        (
            json.dumps(task, indent=2, sort_keys=True),
            json.dumps(json.loads(original["schema_json"]), indent=2),
            rid,
        ),
    )
    store.db.commit()
    before = state(store)
    assert pending_change(store, rid) is None
    assert current_requirement_events(store, rid, "semantic_plan") == []
    assert state(store) == before


@pytest.mark.parametrize("accept", [False, True])
def test_second_pending_proposal_keeps_existing_stale_baseline_policy(ledger, accept):
    _, store, rid = ledger
    propose_change(store, rid, request())
    decide_change(store, rid, accept=accept)
    change = propose_change(store, rid, request(goal="Another proposed goal"))
    damage_contract(store, rid, "goal")
    before = state(store)
    assert pending_change(store, rid) == change
    current_requirement_events(store, rid, "semantic_plan")
    with pytest.raises(VerboisyError, match="proposal is stale"):
        decide_change(store, rid, accept=True)
    assert state(store) == before
