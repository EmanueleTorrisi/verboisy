# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared compound keys must control SmartID, including public API resume."""

import json

import pytest
from verboisy import arun
from verboisy.core.research import ResearchRunner
from verboisy.product import apply_smart_ids
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

KEY = ["/namespace", "/sku"]


@pytest.mark.parametrize(
    "previous,expected",
    [
        ([{"id": 10, "namespace": "north", "sku": "A"}], None),
        (
            [
                {"id": 10, "namespace": "north", "sku": "A"},
                {"id": 20, "namespace": "south", "sku": "A"},
            ],
            20,
        ),
        ([{"id": 10, "sku": "A"}], None),
        ([{"id": 20, "namespace": "south", "sku": "A"}], 20),
        (
            [
                {"id": 20, "namespace": "south", "sku": "A"},
                {"id": "other", "namespace": "south", "sku": "A"},
            ],
            None,
        ),
        ([{"id": 20, "namespace": None, "sku": "A"}], None),
        ([{"id": 20, "namespace": "", "sku": "A"}], None),
    ],
)
def test_compound_key_matching(previous, expected):
    rows, decisions = apply_smart_ids(
        [{"id": 1, "namespace": "south", "sku": "A"}], previous, "previous_id", identity_fields=KEY
    )
    assert rows[0]["previous_id"] == expected
    if expected is not None:
        assert decisions[0]["matched_fields"] == sorted(KEY)


@pytest.mark.parametrize(
    "current", [{"sku": "A"}, {"namespace": "south"}, {"namespace": None, "sku": "A"}]
)
def test_missing_current_component_cannot_fall_back(current):
    rows, _ = apply_smart_ids(
        [{"id": 1, **current}],
        [{"id": 20, "namespace": "south", "sku": "A"}],
        "previous_id",
        identity_fields=KEY,
    )
    assert rows[0]["previous_id"] is None


def test_nested_and_escaped_declared_keys():
    data = {"source": {"a/b": "south"}, "sku": "A"}
    rows, _ = apply_smart_ids(
        [{"id": 1, **data}],
        [{"id": 20, **data}],
        "previous_id",
        identity_fields=["/source/a~1b", "/sku"],
    )
    assert rows[0]["previous_id"] == 20


def test_additional_identifier_contradiction_still_vetoes():
    rows, _ = apply_smart_ids(
        [{"id": 1, "namespace": "south", "sku": "A", "ean": "new"}],
        [{"id": 20, "namespace": "south", "sku": "A", "ean": "old"}],
        "previous_id",
        identity_fields=KEY,
    )
    assert rows[0]["previous_id"] is None


@pytest.mark.asyncio
async def test_api_and_resume_pass_saved_compound_identity(tmp_path, monkeypatch):
    async def completed(self, max_steps):
        self.store.finish(self.rid, "COMPLETED", "target_met", 0, 0)
        return "COMPLETED", "target_met"

    monkeypatch.setattr(ResearchRunner, "run", completed)
    monkeypatch.setattr(
        ResearchStore,
        "records",
        lambda _self, _rid: [{"id": "internal", "namespace": "south", "sku": "A"}],
    )
    monkeypatch.setattr(ResearchStore, "evidence", lambda _self, _rid: [{"record_id": "internal"}])
    previous = tmp_path / "inventory.json"
    previous.write_text(
        json.dumps(
            [
                {"id": 10, "namespace": "north", "sku": "A"},
                {"id": 20, "namespace": "south", "sku": "A"},
            ]
        )
    )
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="disabled"
    )
    first = await arun(
        goal="Fixture inventory",
        schema="[namespace,sku]",
        identity=KEY,
        task={"seed_urls": ["https://example.test/"]},
        smartid=previous,
        config=config,
        export=tmp_path / "first.json",
    )
    assert first.records[0]["inventory_id"] == 20
    second = await arun(resume=first.run_id, config=config, export=tmp_path / "second.json")
    assert second.records == first.records
    store = ResearchStore(config.sqlite_db_path)
    try:
        assert json.loads(store.load(first.run_id)["task_json"])["identity_fields"] == KEY
        for event in store.events(first.run_id, "smartid"):
            assert event["payload"]["decisions"][0]["matched_fields"] == sorted(KEY)
    finally:
        store.close()
