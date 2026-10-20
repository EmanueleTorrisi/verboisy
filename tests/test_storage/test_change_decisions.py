# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exact, durable and atomic user decisions without provider requests."""

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner
from verboisy.api import arun
from verboisy.cli.main import app
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

OLD = {"type": "object", "properties": {"weight": {"type": ["number", "null"]}}}
NEW = {"type": "object", "properties": {"weight": {"type": ["string", "null"]}}}


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    task = TaskSpec(seed_urls=["https://example.test/"], identity_fields=[])
    rid = store.create("Breed weights", OLD, task, None)
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    store.event(rid, "product_options", {"strings": False})
    yield path, store, rid
    store.close()


def request(**updates):
    return {
        "description": "Weight will be a literal range string; no midpoint will be inferred.",
        "goal": "Breed weights",
        "schema": NEW,
        "task": TaskSpec(seed_urls=["https://example.test/"]).model_dump(),
        **updates,
    }


@pytest.mark.parametrize("accept", [True, False])
def test_exact_decision_durable_and_no_accounting_reset(ledger, accept):
    path, store, rid = ledger
    original = store.load(rid)
    change = propose_change(store, rid, request())
    assert store.load(rid)["schema_json"] == original["schema_json"]
    assert store.load(rid)["reason"] == "proposed_changes"
    store.close()
    with_read = ResearchStore(str(path), read_only=True)
    assert pending_change(with_read, rid) == change
    with_read.close()
    store = ResearchStore(str(path))
    try:
        assert decide_change(store, rid, accept=accept) == change
        state = store.load(rid)
        assert json.loads(state["schema_json"]) == (NEW if accept else OLD)
        assert (state["tokens"], state["reserved"]) == (17, 796)
        assert state["reason"] is None
        assert pending_change(store, rid) is None
        decision = store.events(rid, "change_decided")[-1]["payload"]
        assert decision["previous_requirements"]["schema"] == OLD
        assert decision["proposal_id"] == change.proposal_id
        assert decision["decision"] == ("accepted" if accept else "declined")
        assert len(store.events(rid, "change_proposed")) == 1
        assert decide_change(store, rid, accept=False) is None
        with pytest.raises(VerboisyError, match="No pending"):
            decide_change(store, rid, accept=True)
    finally:
        store.close()


@pytest.mark.parametrize(
    "updates",
    [
        {"schema": {"type": "integer"}},
        {"schema": {"type": "object", "properties": {"x": {"$ref": "https://bad/"}}}},
        {"task": {"unknown": True}},
        {"description": ""},
        {"description": " "},
        {"goal": " "},
        {"goal": "Breed weights", "schema": OLD},
        {"unknown": True},
    ],
)
def test_invalid_and_noop_proposals_do_not_write(ledger, updates):
    _, store, rid = ledger
    before = store.load(rid)
    events = store.events(rid)
    with pytest.raises(VerboisyError):
        propose_change(store, rid, request(**updates))
    assert store.load(rid) == before
    assert store.events(rid) == events


def test_pending_proposal_cannot_be_silently_replaced(ledger):
    _, store, rid = ledger
    change = propose_change(store, rid, request())
    with pytest.raises(VerboisyError, match="Resolve"):
        propose_change(store, rid, request(goal="Other goal"))
    assert pending_change(store, rid) == change


@pytest.mark.parametrize("phase", ["offer", "accept"])
@pytest.mark.parametrize("blocked", ["completed", "records", "stale"])
def test_unavailable_or_stale_contract_rejected(ledger, phase, blocked):
    _, store, rid = ledger
    if phase == "accept":
        propose_change(store, rid, request())
    if blocked == "completed":
        store.finish(rid, "COMPLETED", None, 17, 796)
    elif blocked == "records":
        store.db.execute("INSERT INTO records(run_id,payload) VALUES (?, '{}')", (rid,))
        store.db.commit()
    else:
        if phase == "offer":
            return
        store.db.execute("UPDATE research_runs SET goal='changed' WHERE id=?", (rid,))
        store.db.commit()
    before = store.load(rid)
    with pytest.raises(VerboisyError):
        if phase == "offer":
            propose_change(store, rid, request())
        else:
            decide_change(store, rid, accept=True)
    assert store.load(rid) == before
    assert not store.events(rid, "change_decided")


def test_corrupt_saved_proposal_fails_closed(ledger):
    _, store, rid = ledger
    store.event(rid, "change_proposed", {"bad": "payload"})
    with pytest.raises(VerboisyError, match="Invalid saved"):
        pending_change(store, rid)


@pytest.mark.parametrize("stage", ["offer", "decision"])
def test_transaction_rolls_back_on_journal_failure(ledger, stage):
    _, store, rid = ledger
    if stage == "decision":
        propose_change(store, rid, request())
    state = store.load(rid)
    events = store.events(rid)
    kind = "change_proposed" if stage == "offer" else "change_decided"
    store.db.execute(
        f"CREATE TRIGGER reject_change BEFORE INSERT ON events WHEN NEW.kind='{kind}' "
        "BEGIN SELECT RAISE(ABORT, 'fixture'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        if stage == "offer":
            propose_change(store, rid, request())
        else:
            decide_change(store, rid, accept=True)
    assert store.load(rid) == state
    assert store.events(rid) == events


def test_semantic_history_retained_but_old_plan_not_reused(ledger):
    _, store, rid = ledger
    store.event(rid, "field_semantics_plan", {"old": True})
    assert len(current_requirement_events(store, rid, "field_semantics_plan")) == 1
    propose_change(store, rid, request())
    decide_change(store, rid, accept=True)
    assert current_requirement_events(store, rid, "field_semantics_plan") == []
    runner = ResearchRunner(store, rid, Settings(_env_file=None))
    assert runner.schema == NEW and not runner.semantic_plan_ready
    store.event(rid, "field_semantics_plan", {"new": True})
    assert current_requirement_events(store, rid, "field_semantics_plan")[0]["payload"] == {
        "new": True
    }
    assert len(store.events(rid, "field_semantics_plan")) == 2
    propose_change(store, rid, request(schema=OLD))
    decide_change(store, rid, accept=False)
    assert len(current_requirement_events(store, rid, "field_semantics_plan")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [True, False])
async def test_api_decision_precedes_research(ledger, monkeypatch, accept):
    path, store, rid = ledger
    propose_change(store, rid, request())
    store.close()
    captured = []

    async def offline_run(runner, steps):
        captured.append(runner.schema)
        runner.store.finish(rid, "PAUSED", "fixture", 17, 796)

    monkeypatch.setattr(ResearchRunner, "run", offline_run)
    result = await arun(
        **({"okresume": rid} if accept else {"resume": rid}),
        config=Settings(_env_file=None, sqlite_db_path=str(path)),
    )
    assert result.status == "PAUSED"
    assert result.notices[0].startswith("* Accepted" if accept else "* Proposed changes declined")
    assert captured == [NEW if accept else OLD]
    with_read = ResearchStore(str(path), read_only=True)
    assert pending_change(with_read, rid) is None
    with_read.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"okresume": " "},
        {"okresume": 1},
        {"resume": "rid", "okresume": "rid"},
        {"okresume": "rid", "schema": OLD},
    ],
)
async def test_api_invalid_resume_inputs_do_not_create_database(tmp_path, kwargs):
    path = tmp_path / "absent.db"
    with pytest.raises(VerboisyError):
        await arun(config=Settings(_env_file=None, sqlite_db_path=str(path)), **kwargs)
    assert not path.exists()


def test_cli_submit_inspect_and_no_pending(ledger, tmp_path, monkeypatch):
    path, store, rid = ledger
    monkeypatch.setenv("SQLITE_DB_PATH", str(path))
    cli = CliRunner()
    result = cli.invoke(app, ["changes", "--run-id", rid])
    assert result.exit_code == 0 and "⟡ No pending" in result.output
    file = tmp_path / "change.json"
    file.write_text(json.dumps(request()), encoding="utf-8")
    store.close()
    result = cli.invoke(app, ["changes", "--run-id", rid, "--proposal", str(file)])
    assert result.exit_code == 0, result.output
    assert "⟡ Proposed changes:" in result.output
    assert f"--okresume {rid}" in result.output
    result = cli.invoke(app, ["changes", "--run-id", rid, "--database", str(path)])
    assert result.exit_code == 0
    assert '"schema"' in result.output and '"type": "string"' not in result.output
    assert '"string"' in result.output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--run-id", " "],
        ["--run-id", "missing"],
        ["--run-id", "missing", "--proposal", "absent.json"],
    ],
)
def test_cli_bad_inspection_is_safe(tmp_path, arguments):
    path = tmp_path / "missing.db"
    result = CliRunner().invoke(app, ["changes", "--database", str(path), *arguments])
    assert result.exit_code == 1
    assert not path.exists()


@pytest.mark.parametrize("flag", ["--okresume", "--okresume=run-id"])
def test_cli_optional_value_routes_to_api(monkeypatch, flag):
    import verboisy.cli.main as cli

    def check(**kwargs):
        assert kwargs["resume"] is False
        assert kwargs["okresume"] == (True if flag == "--okresume" else "run-id")
        raise VerboisyError("fixture stop before execution")

    monkeypatch.setattr(cli, "run", check)
    result = CliRunner().invoke(app, ["run", flag])
    assert result.exit_code == 1
    assert "fixture stop" in result.output


@pytest.mark.asyncio
async def test_no_pending_okresume_does_not_start_provider(ledger, monkeypatch):
    path, store, rid = ledger
    store.close()
    execution = AsyncMock()
    monkeypatch.setattr(ResearchRunner, "run", execution)
    with pytest.raises(VerboisyError, match="No pending"):
        await arun(okresume=rid, config=Settings(_env_file=None, sqlite_db_path=str(path)))
    execution.assert_not_awaited()


def test_acceptance_requeues_previous_work_and_adds_new_seeds(ledger):
    _, store, rid = ledger
    store.queue(rid, "https://example.test/old", 1, None)
    store.db.execute("UPDATE pages SET status='done' WHERE run_id=?", (rid,))
    store.db.commit()
    old_page = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()["id"]
    task = TaskSpec(seed_urls=["https://example.test/new"])
    propose_change(store, rid, request(task=task.model_dump()))
    decide_change(store, rid, accept=True)
    pages = store.db.execute("SELECT id,url,status FROM pages WHERE run_id=?", (rid,)).fetchall()
    assert len(pages) == 2 and all(p["status"] == "queued" for p in pages)
    assert any(p["id"] == old_page for p in pages)
    assert len(store.events(rid, "research_plan")) == 1


@pytest.mark.parametrize("stage", ["existing", "proposed", "corrupt_saved"])
def test_dataset_changes_require_reingestion_workflow(ledger, stage):
    _, store, rid = ledger
    dataset_task = TaskSpec(dataset_sources=[{"url": "https://example.test/data", "format": "csv"}])
    if stage == "existing":
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (dataset_task.model_dump_json(), rid)
        )
        store.db.commit()
    elif stage == "corrupt_saved":
        change = propose_change(store, rid, request())
        payload = change.model_dump(mode="json", by_alias=True)
        payload["request"]["task"] = dataset_task.model_dump()
        store.db.execute(
            "UPDATE events SET payload=? WHERE run_id=? AND kind='change_proposed'",
            (json.dumps(payload), rid),
        )
        store.db.commit()
    with pytest.raises(VerboisyError, match="workflow|browser"):
        if stage == "corrupt_saved":
            decide_change(store, rid, accept=True)
        else:
            propose_change(store, rid, request(task=dataset_task.model_dump()))
