# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Range offers require observed intervals, preserve requirements and never invent values."""

import copy
import json

import pytest
from verboisy.evidence.models import (
    Candidate,
    PageProposal,
    RangeConflict,
    Snapshot,
    Source,
    TaskSpec,
)
from verboisy.extractor.range_changes import (
    candidate_range_conflicts,
    interval_quote,
    offer_range_change,
    offer_saved_range_change,
)
from verboisy.storage.changes import decide_change, pending_change, propose_change
from verboisy.storage.research import ResearchStore

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"name": {"type": "string"}, "weight": {"type": ["number", "null"]}},
    "required": ["name", "weight"],
}


@pytest.fixture
def ledger(tmp_path):
    store = ResearchStore(str(tmp_path / "runs.db"))
    rid = store.create("Typical weights", SCHEMA, TaskSpec(identity_fields=["/name"]), None)
    store.finish(rid, "PAUSED", "model_request_budget", 17, 796)
    yield store, rid
    store.close()


def page(text="Male weight: 45 - 55 kg", **updates):
    return Snapshot(
        id="snapshot",
        url="https://example.test/",
        fetched_at="2026-01-01",
        content_hash="fixture",
        truncated=False,
        sources=[Source(id="e1", scope="s1", kind="text", text=text, **updates)],
    )


def conflict(**updates):
    return RangeConflict(pointer="/weight", scope="s1", source="e1", quote="45 - 55 kg", **updates)


@pytest.mark.parametrize(
    "quote",
    [
        "45 - 55 kg",
        "45\u201355 kg",
        "45\u201455kg",
        "45 to 55 kg",
        "45 kg - 55 kg",
        "-10 - -5 °C",
        "1,000 - 2,000 m",
        "1.5 - 2.5 m",
        "45 - 55",
        " 45  -  55 kg ",
    ],
)
def test_complete_intervals_preserve_original_text(quote):
    assert interval_quote(quote) == quote


@pytest.mark.parametrize(
    "quote",
    [
        "over 100 pounds",
        "100",
        "100 - 100 kg",
        "55 - 45 kg",
        "45 kg - 55 lbs",
        "2026-01-02",
        "Male weights: 45 - 55 kg",
        "1.5.6 - 2.5",
        "NaN - Infinity",
        "45 +/- 5 kg",
        "about 45 - 55 kg",
        "",
        "10e3 - 20e3",
    ],
)
def test_incomplete_ambiguous_or_reversed_values_not_complete_intervals(quote):
    assert interval_quote(quote) is None


@pytest.mark.parametrize("array", [True, False])
@pytest.mark.parametrize("nullable", [True, False])
def test_offer_changes_only_type_and_keeps_context_and_budget(ledger, array, nullable):
    store, rid = ledger
    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["weight"]["type"] = ["integer", "null"] if nullable else "integer"
    schema["properties"]["weight"]["description"] = "Typical male weight"
    schema = {"type": "array", "items": schema} if array else schema
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    change = offer_range_change(store, rid, page(), [conflict()])
    assert change is not None
    original = store.load(rid)
    assert json.loads(original["schema_json"]) == schema
    assert (original["tokens"], original["reserved"]) == (17, 796)
    target = change.request.schema_["items"] if array else change.request.schema_
    assert target["properties"]["weight"]["type"] == (["string", "null"] if nullable else "string")
    assert target["properties"]["name"] == SCHEMA["properties"]["name"]
    assert target["properties"]["weight"]["description"] == "Typical male weight"
    assert change.request.evidence[0].model_dump() == {
        "pointer": "/weight",
        "snapshot_id": "snapshot",
        "scope": "s1",
        "source": "e1",
        "quote": "45 - 55 kg",
    }
    assert "all sources" in change.request.description
    assert "min/max" in change.request.description


@pytest.mark.parametrize("pointer", ["/missing", "/nested/weight", "weight", "/" + "w" * 201])
def test_unavailable_nested_and_oversized_pointers_not_offered(ledger, pointer):
    store, rid = ledger
    item = conflict().model_copy(update={"pointer": pointer})
    assert offer_range_change(store, rid, page(), [item]) is None


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string"},
        {"type": "null"},
        {"type": "number", "minimum": 1},
        {"type": "number", "enum": [45, 55]},
        True,
    ],
)
def test_explicit_constraints_and_non_numeric_fields_not_rewritten(ledger, field):
    store, rid = ledger
    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["weight"] = field
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    assert offer_range_change(store, rid, page(), [conflict()]) is None


@pytest.mark.parametrize(
    "rule",
    [
        {"mapping": {"45": "45 - 55 kg"}},
        {"source": "link"},
        {"external": True},
    ],
)
def test_authoritative_field_rules_not_overridden(ledger, rule):
    store, rid = ledger
    task = TaskSpec(field_rules={"/weight": rule})
    store.db.execute(
        "UPDATE research_runs SET task_json=? WHERE id=?", (task.model_dump_json(), rid)
    )
    store.db.commit()
    assert offer_range_change(store, rid, page(), [conflict()]) is None


@pytest.mark.parametrize(
    "updates",
    [
        {"source": "invented"},
        {"scope": "s2"},
        {"quote": "46 - 56 kg"},
        {"quote": "over 100 pounds"},
    ],
)
def test_observation_must_be_present_in_named_scope_and_source(ledger, updates):
    store, rid = ledger
    item = conflict().model_copy(update=updates)
    assert offer_range_change(store, rid, page(), [item]) is None


def test_hyperlinks_and_dates_not_treated_as_measurements(ledger):
    store, rid = ledger
    link_page = page().model_copy(
        update={
            "sources": [
                Source(
                    id="e1",
                    scope="s1",
                    kind="link",
                    text="45 - 55 kg",
                    href="https://example.test/",
                )
            ]
        }
    )
    assert offer_range_change(store, rid, link_page, [conflict()]) is None
    date = conflict().model_copy(update={"quote": "02\u201303"})
    assert offer_range_change(store, rid, page("2026\u201302\u201303"), [date]) is None


@pytest.mark.parametrize(
    "blocked", ["empty", "completed", "records", "dataset", "identity", "pending"]
)
def test_unavailable_runs_do_not_get_a_new_offer(ledger, blocked):
    store, rid = ledger
    items = [conflict()]
    if blocked == "empty":
        items = []
    elif blocked == "completed":
        store.finish(rid, "COMPLETED", None, 17, 796)
    elif blocked == "records":
        captured = page("Example weighs 50 kg")
        store.queue(rid, captured.url, 0, None)
        work = store.next_page(rid)
        store.snapshot(rid, work["id"], captured, "Example weighs 50 kg")
        candidate = Candidate(
            scope="s1",
            record={"name": "Example", "weight": 50},
            evidence={
                "/name": {"source": "e1", "quote": "Example", "transform": "text"},
                "/weight": {"source": "e1", "quote": "50", "transform": "number"},
            },
        )
        store.accept(rid, captured, candidate, [], TaskSpec(identity_fields=["/name"]))
    elif blocked in {"dataset", "identity"}:
        task = (
            TaskSpec(dataset_sources=[{"url": "https://example.test/", "format": "csv"}])
            if blocked == "dataset"
            else TaskSpec(identity_fields=["/weight"])
        )
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (task.model_dump_json(), rid)
        )
        store.db.commit()
    else:
        propose_change(
            store,
            rid,
            {
                "description": "Manual offer",
                "schema": SCHEMA,
                "goal": "Other goal",
                "task": TaskSpec().model_dump(),
            },
        )
    before = store.events(rid)
    assert offer_range_change(store, rid, page(), items) is None
    assert store.events(rid) == before


def test_declined_contract_is_not_reoffered(ledger):
    store, rid = ledger
    assert offer_range_change(store, rid, page(), [conflict()]) is not None
    decide_change(store, rid, accept=False)
    assert pending_change(store, rid) is None
    assert offer_range_change(store, rid, page(), [conflict()]) is None
    # A different replacement contract remains eligible.
    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["height"] = {"type": "number"}
    state = store.load(rid)
    propose_change(
        store,
        rid,
        {
            "description": "Include typical height",
            "schema": schema,
            "goal": state["goal"],
            "task": json.loads(state["task_json"]),
        },
    )
    decide_change(store, rid, accept=True)
    items = [conflict(), conflict().model_copy(update={"pointer": "/height"})]
    assert offer_range_change(store, rid, page(), items) is not None


def test_escaped_property_names_and_semantics_preserved(ledger):
    store, rid = ledger
    schema = {
        "type": "object",
        "properties": {"size/value": {"type": "number", "x-verboisy-unit-sensitive": True}},
    }
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    item = conflict().model_copy(update={"pointer": "/size~1value"})
    change = offer_range_change(store, rid, page(), [item, item])
    assert change is not None and len(change.request.evidence) == 1
    assert change.request.schema_["properties"]["size/value"]["x-verboisy-unit-sensitive"] is True


def test_legacy_numeric_proofs_provide_grounded_conflict_signals():
    candidate = Candidate(
        scope="s1",
        record={"name": "Example", "weight": 50},
        evidence={
            "/name": {"source": "e0", "quote": "Example", "transform": "text"},
            "/weight": {
                "source": "e1",
                "quote": "Typical weight is 45 - 55 kg",
                "transform": "number",
            },
        },
    )
    conflicts = candidate_range_conflicts(PageProposal(candidates=[candidate]))
    assert conflicts == [conflict()]
    candidate.evidence["/weight"].quote = "100 - 100 kg; over 100 pounds"
    assert candidate_range_conflicts(PageProposal(candidates=[candidate])) == []


def test_saved_candidates_scan_is_run_scoped_and_needs_no_provider(ledger):
    store, rid = ledger
    candidate = Candidate(
        scope="s1",
        record={"name": "Example", "weight": 50},
        evidence={"/weight": {"source": "e1", "quote": "45 - 55 kg", "transform": "number"}},
    )
    captured = page()
    store.queue(rid, captured.url, 0, None)
    work = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()
    store.snapshot(rid, work["id"], captured, "Male weight: 45 - 55 kg")
    store.db.execute(
        "INSERT INTO candidates(run_id,snapshot_id,payload,accepted) VALUES (?,?,?,0)",
        (rid, page().id, candidate.model_dump_json()),
    )
    # Missing snapshots are ignored, not fetched.
    store.db.execute(
        "INSERT INTO candidates(run_id,payload,accepted) VALUES (?, ?,0)",
        (rid, candidate.model_dump_json()),
    )
    store.db.commit()
    assert offer_saved_range_change(store, rid) is not None
    assert offer_saved_range_change(store, rid) is None
    other = store.create("Other", SCHEMA, TaskSpec(), None)
    assert offer_saved_range_change(store, other) is None
