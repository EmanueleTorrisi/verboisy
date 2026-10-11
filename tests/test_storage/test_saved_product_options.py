# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Saved shaping settings must fail before resume publishes requirement decisions."""

import json
from unittest.mock import patch

import pytest
from verboisy import arun
from verboisy.evidence.models import TaskSpec
from verboisy.storage.changes import propose_change
from verboisy.storage.product_options import saved_export_destinations, saved_product_options
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA

BAD_OPTIONS = [
    None,
    [],
    "options",
    {"strings": "false"},
    {"strings": 1},
    {"proof": "false"},
    {"proof": 0},
    {"research": "true"},
    {"schema_inferred": 1},
    {"groupby": 7},
    {"groupby": " "},
    {"smartid": True},
    {"smartid": " "},
    {"order": None},
    {"order": {}},
    {"order": ["name"]},
    {"order": [{"field": 1}]},
    {"order": [{"field": " "}]},
    {"order": [{"field": "name", "direction": "up"}]},
    {"source_policy": None},
    {"source_policy": {"include": "example.test"}},
    {"source_policy": {"include": [1]}},
    {"source_policy": {"include": ["bad/domain"]}},
    {"source_policy": {"onlyinclude": "false"}},
    {"source_policy": {"onlyinclude": True}},
]
BAD_EXPORTS = [
    '{"rows.json":1}',
    "[1]",
    "[true]",
    "true",
    "17",
    "NaN",
    "Infinity",
    "1e9999",
    '{"x":1,"x":2}',
    '["rows.json",null]',
]


@pytest.mark.parametrize("value", BAD_OPTIONS)
def test_invalid_option_values_are_rejected_without_coercion(value):
    with pytest.raises(VerboisyError, match="Saved product options failed integrity"):
        saved_product_options([{"payload": value}])


@pytest.mark.parametrize("payload", BAD_EXPORTS)
def test_invalid_destination_json_is_rejected(payload):
    with pytest.raises(VerboisyError, match="Saved export destinations failed integrity"):
        saved_export_destinations(payload)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"strings": False},
        {"proof": True},
        {"order": [{"field": "name"}]},
        {"source_policy": {"include": ["example.test"], "onlyinclude": True}},
        {"historical_extension": {"value": 1}},
    ],
)
def test_legacy_defaults_and_valid_settings_remain_independent(value):
    original = json.dumps(value)
    result = saved_product_options([{"payload": value}])
    result["source_policy"]["include"].append("other.test")
    result["order"].append({"field": "changed", "direction": "asc"})
    assert json.dumps(value) == original
    assert saved_product_options([{"payload": value}])["strings"] is value.get("strings", False)


def test_missing_options_use_defaults():
    assert saved_product_options([])["order"] == []


@pytest.mark.parametrize(
    "payload,expected",
    [
        (None, None),
        ("", None),
        ("null", None),
        ('"rows.json"', "rows.json"),
        ("[]", []),
        ('["rows.json","rows.csv"]', ["rows.json", "rows.csv"]),
    ],
)
def test_valid_destination_representations_are_preserved(payload, expected):
    assert saved_export_destinations(payload) == expected


@pytest.mark.parametrize(
    "kind,value",
    [("options", v) for v in BAD_OPTIONS]
    + [("exports", v) for v in BAD_EXPORTS]
    + [("exports", '["same.json","same.json"]'), ("exports", '["invalid.txt"]')],
)
@pytest.mark.parametrize("accept", [False, True])
async def test_resume_preflight_preserves_pending_decision_and_export_files(
    tmp_path, kind, value, accept
):
    path = tmp_path / "run.db"
    store = ResearchStore(path)
    task = TaskSpec(seed_urls=["https://example.test/"])
    rid = store.create("People", SCHEMA, task, None)
    propose_change(
        store,
        rid,
        {
            "description": "Use text ages",
            "goal": "People with age ranges",
            "schema": SCHEMA,
            "task": task.model_dump(),
        },
    )
    if kind == "options":
        store.event(rid, "product_options", value)
    else:
        store.db.execute("UPDATE research_runs SET export_path=? WHERE id=?", (value, rid))
        store.db.commit()
    before = {
        table: [tuple(r) for r in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in ("research_runs", "events", "pages", "candidates", "records")
    }
    store.close()
    output = tmp_path / "rows.json"
    output.write_bytes(b"existing generation")
    with (
        patch("verboisy.api.decide_change", side_effect=AssertionError("decision reached")),
        pytest.raises(VerboisyError),
    ):
        await arun(
            resume=False if accept else rid,
            okresume=rid if accept else False,
            config=Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled"),
        )
    store = ResearchStore(path)
    try:
        after = {
            table: [tuple(r) for r in store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in before
        }
        assert after == before
        assert output.read_bytes() == b"existing generation"
    finally:
        store.close()
