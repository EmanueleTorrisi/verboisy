# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved requirement ambiguity must stop before decisions or export publication."""

import json
from unittest.mock import patch

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.diagnostics import inspect_research_runs, inspect_research_status
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA

INVALID = [
    '{"value":1,"value":2}',
    '{"value":1,"value":1}',
    '{"value":1,"\\u0076alue":2}',
    '{"nested":{"value":1,"value":2}}',
    '{"nested":[{"value":1,"value":2}]}',
    '{"value":NaN}',
    '{"value":Infinity}',
    '{"value":-Infinity}',
    '{"value":1e9999}',
    '{"value":-1e9999}',
    "[]",
    "null",
    "true",
    '"object"',
]


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "run.sqlite3"
    store = ResearchStore(path)
    rid = store.create("Saved research", SCHEMA, TaskSpec(), None)
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    store.close()
    return path, rid


def ledger_state(store):
    return {
        table: [tuple(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("research_runs", "events", "pages", "candidates", "records", "snapshots")
    }


@pytest.mark.parametrize("field", ["schema_json", "task_json"])
@pytest.mark.parametrize("payload", INVALID)
@pytest.mark.parametrize("operation", ["load", "latest", "runner", "export"])
def test_ambiguous_requirements_stop_before_use(saved, tmp_path, field, payload, operation):
    path, rid = saved
    store = ResearchStore(path)
    try:
        store.db.execute(f"UPDATE research_runs SET {field}=? WHERE id=?", (payload, rid))
        store.db.commit()
        before = ledger_state(store)
        destination = tmp_path / "rows.json"
        manifest = tmp_path / "rows.json.manifest.json"
        destination.write_bytes(b"old output")
        manifest.write_bytes(b"old manifest")
        files_before = {p.name: p.read_bytes() for p in tmp_path.glob("rows*")}
        with pytest.raises(VerboisyError, match="Saved (task|schema) failed integrity"):
            if operation == "load":
                store.load(rid)
            elif operation == "latest":
                store.load(None)
            elif operation == "runner":
                ResearchRunner(store, rid, Settings(_env_file=None, search_provider="disabled"))
            else:
                export_dataset(store, rid, destination, SCHEMA, TaskSpec(), rows=[])
        assert ledger_state(store) == before
        assert {p.name: p.read_bytes() for p in tmp_path.glob("rows*")} == files_before
    finally:
        store.close()


@pytest.mark.parametrize("field", ["schema_json", "task_json"])
@pytest.mark.parametrize("payload", INVALID)
def test_read_only_status_rejects_ambiguous_run_without_writes(saved, field, payload):
    path, rid = saved
    store = ResearchStore(path)
    store.db.execute(f"UPDATE research_runs SET {field}=? WHERE id=?", (payload, rid))
    store.db.commit()
    store.close()
    before = path.read_bytes()
    with pytest.raises(VerboisyError, match="Saved (task|schema) failed integrity"):
        inspect_research_status(path, rid)
    assert path.read_bytes() == before


@pytest.mark.parametrize("payload", INVALID)
def test_run_inventory_marks_ambiguous_task_without_hiding_run(saved, payload):
    path, rid = saved
    store = ResearchStore(path)
    store.db.execute("UPDATE research_runs SET task_json=? WHERE id=?", (payload, rid))
    store.db.commit()
    store.close()
    before = path.read_bytes()
    result = inspect_research_runs(path)
    assert result["runs"][0]["run_id"] == rid
    assert result["runs"][0]["repair_inspection"] == "invalid_task"
    assert result["runs"][0]["dataset_source_count"] is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["schema_json", "task_json"])
@pytest.mark.parametrize("style", ["compact", "indented", "unicode", "reordered"])
def test_valid_historical_text_is_retained_exactly(saved, field, style):
    path, rid = saved
    store = ResearchStore(path)
    try:
        original = store.load(rid)
        value = json.loads(original[field])
        if style == "unicode":
            if field == "schema_json":
                value["title"] = "Café 李雷"
            else:
                value["identity_fields"] = ["/Café"]
        if style == "reordered":
            value = dict(reversed(list(value.items())))
        payload = json.dumps(value, ensure_ascii=False, indent=2 if style == "indented" else None)
        store.db.execute(f"UPDATE research_runs SET {field}=? WHERE id=?", (payload, rid))
        store.db.commit()
        before = ledger_state(store)
        assert store.load(rid)[field] == payload
        assert store.load(None)[field] == payload
        assert ledger_state(store) == before
    finally:
        store.close()


@pytest.mark.parametrize("resume", [True, "id"])
async def test_resume_preflight_never_applies_decision_or_presentation(saved, resume):
    from verboisy import arun

    path, rid = saved
    store = ResearchStore(path)
    store.db.execute(
        "UPDATE research_runs SET task_json=? WHERE id=?",
        ('{"identity_fields":[],"identity_fields":[]}', rid),
    )
    store.db.commit()
    before = ledger_state(store)
    store.close()
    with (
        patch("verboisy.api.decide_change", side_effect=AssertionError("decision reached")),
        pytest.raises(VerboisyError, match="Saved (task|schema) failed integrity"),
    ):
        await arun(
            resume=rid if resume == "id" else True,
            config=Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled"),
        )
    store = ResearchStore(path)
    try:
        assert ledger_state(store) == before
    finally:
        store.close()
