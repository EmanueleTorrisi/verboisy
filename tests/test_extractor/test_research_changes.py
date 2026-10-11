# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Evidence-backed alternatives require consent and preserve collection policy."""

import copy
import json

import pytest
from verboisy.evidence.models import ResearchSuggestion, TaskSpec
from verboisy.extractor.research_changes import offer_research_change
from verboisy.storage.changes import decide_change, propose_change

from tests.test_extractor.test_range_changes import SCHEMA, ledger, page

__all__ = ["ledger"]


def suggestion(**updates):
    value = {
        "goal": "Research city restrictions",
        "columns": {"city": {"type": "string"}},
        "drop_columns": ["weight"],
        "evidence": [
            {"pointer": pointer, "scope": "s1", "source": "e1", "quote": "City restrictions"}
            for pointer in ["/", "/city", "/weight"]
        ],
    }
    value.update(updates)
    return ResearchSuggestion.model_validate(value)


@pytest.mark.parametrize("array", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_exact_offer_and_decision_preserve_policy_and_accounting(ledger, array, accept):
    store, rid = ledger
    schema = {"type": "array", "items": SCHEMA} if array else SCHEMA
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    before = store.load(rid)
    result = offer_research_change(store, rid, page("City restrictions"), [suggestion()])
    assert result is not None
    record = result.request.schema_["items"] if array else result.request.schema_
    assert set(record["properties"]) == {"name", "city"}
    assert (
        result.request.task.model_dump_json()
        == TaskSpec.model_validate_json(before["task_json"]).model_dump_json()
    )
    assert "Added columns: ['city']" in result.request.description
    assert len(result.request.evidence) == 3
    assert store.load(rid)["goal"] == before["goal"]
    decide_change(store, rid, accept=accept)
    after = store.load(rid)
    assert after["tokens"] == before["tokens"]
    assert after["reserved"] == before["reserved"]
    assert after["goal"] == (result.request.goal if accept else before["goal"])
    if not accept:
        assert offer_research_change(store, rid, page("City restrictions"), [suggestion()]) is None


@pytest.mark.parametrize(
    "updates",
    [
        {"goal": " "},
        {"drop_columns": ["missing"]},
        {"drop_columns": ["city"]},
        {"drop_columns": ["name"]},
        {"columns": {"name": {"type": "integer"}}},
        {"columns": {" ": {"type": "string"}}},
        {"columns": {"x" * 101: {"type": "string"}}},
        {"columns": {"city": {"type": "invalid"}}},
        {"columns": {"city": {"$ref": "https://example.test/schema"}}},
        {"goal": None, "columns": {}, "drop_columns": []},
        {"columns": {"weight": {"type": "string"}}},
    ],
)
def test_invalid_or_protected_contract_not_offered(ledger, updates):
    store, rid = ledger
    assert (
        offer_research_change(store, rid, page("City restrictions"), [suggestion(**updates)])
        is None
    )


@pytest.mark.parametrize(
    "update",
    [
        {"source": "missing"},
        {"scope": "wrong"},
        {"quote": "not observed"},
        {"quote": " "},
        {"pointer": "/unrelated"},
    ],
)
def test_every_change_requires_observed_scoped_quote(ledger, update):
    store, rid = ledger
    value = suggestion().model_dump()
    value["evidence"][0].update(update)
    assert (
        offer_research_change(
            store, rid, page("City restrictions"), [ResearchSuggestion.model_validate(value)]
        )
        is None
    )


def test_link_text_not_research_evidence(ledger):
    store, rid = ledger
    snapshot = page("City restrictions")
    snapshot.sources[0].kind = "link"
    assert offer_research_change(store, rid, snapshot, [suggestion()]) is None


@pytest.mark.parametrize("ineligible", ["completed", "dataset", "records", "pending", "field_rule"])
def test_ineligible_runs_remain_unchanged(ledger, ineligible, monkeypatch):
    store, rid = ledger
    if ineligible == "completed":
        store.finish(rid, "COMPLETED", "target_met", 17, 796)
    elif ineligible in {"dataset", "field_rule"}:
        task = (
            TaskSpec(dataset_sources=[{"url": "https://example.test/x.csv", "format": "csv"}])
            if ineligible == "dataset"
            else TaskSpec(field_rules={"/weight": {}})
        )
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (task.model_dump_json(), rid)
        )
        store.db.commit()
    elif ineligible == "records":
        monkeypatch.setattr(store, "records", lambda _: [{"name": "Example"}])
    else:
        propose_change(
            store,
            rid,
            {"description": "Existing", "goal": "Other goal", "schema": SCHEMA, "task": TaskSpec()},
        )
    assert offer_research_change(store, rid, page("City restrictions"), [suggestion()]) is None


def test_empty_signals_do_not_touch_store():
    assert offer_research_change(None, "unused", page(), []) is None


def test_type_change_and_goal_only_with_escaped_names(ledger):
    store, rid = ledger
    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["a/b~c"] = schema["properties"].pop("weight")
    schema["required"] = ["name", "a/b~c"]
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    value = suggestion(
        goal=None,
        columns={"a/b~c": {"type": "string"}},
        drop_columns=[],
        evidence=[
            {"pointer": "/a~1b~0c", "scope": "s1", "source": "e1", "quote": "City restrictions"}
        ],
    )
    result = offer_research_change(store, rid, page("City restrictions"), [value])
    assert result.request.goal == "Typical weights"
    assert "changed columns: ['a/b~c']" in result.request.description
    decide_change(store, rid, accept=True)
    result = offer_research_change(
        store,
        rid,
        page("City restrictions"),
        [
            suggestion(
                columns={},
                drop_columns=[],
                evidence=[
                    {"pointer": "/", "scope": "s1", "source": "e1", "quote": "City restrictions"}
                ],
            )
        ],
    )
    assert result is not None


def test_nested_identity_and_field_rules_protect_parent_columns(ledger):
    store, rid = ledger
    for task in (
        TaskSpec(identity_fields=["/weight/value"]),
        TaskSpec(field_rules={"/weight/value": {}}),
    ):
        store.db.execute(
            "UPDATE research_runs SET task_json=? WHERE id=?", (task.model_dump_json(), rid)
        )
        store.db.commit()
        assert offer_research_change(store, rid, page("City restrictions"), [suggestion()]) is None


def test_changed_optional_column_stays_optional(ledger):
    store, rid = ledger
    schema = copy.deepcopy(SCHEMA)
    schema["required"] = ["name"]
    store.db.execute("UPDATE research_runs SET schema_json=? WHERE id=?", (json.dumps(schema), rid))
    store.db.commit()
    value = suggestion(
        goal=None,
        columns={"weight": {"type": "string"}},
        drop_columns=[],
        evidence=[
            {"pointer": "/weight", "scope": "s1", "source": "e1", "quote": "City restrictions"}
        ],
    )
    result = offer_research_change(store, rid, page("City restrictions"), [value])
    assert result.request.schema_["required"] == ["name"]
