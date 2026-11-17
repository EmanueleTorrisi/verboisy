# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check typed identity, lineage and reference admission through the public API."""

import json
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from verboisy import arun
from verboisy.product import apply_smart_ids
from verboisy.storage.changes import pending_change, propose_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError, VerboisyError

SCHEMA = {
    "type": "object",
    "properties": {
        "sku": {"type": "integer"},
        "site": {"type": "string"},
        "amount": {"type": "integer"},
    },
    "required": ["sku", "site", "amount"],
}


@pytest.mark.parametrize(
    ("incoming", "previous"),
    [
        (
            {"name": "Ava", "city": "Rome"},
            [
                {"id": 1, "name": "Ava", "city": "Madrid"},
                {"id": 2, "name": "Ava", "city": "Berlin"},
                {"id": 3, "name": "Bea", "city": "Rome"},
            ],
        ),
        (
            {"name": "Ava", "city": "Rome", "employer": None},
            [{"id": 1, "name": "Ava", "city": "Rome", "employer": "Lab"}],
        ),
    ],
)
def test_index_hits_are_not_identity_proof(incoming, previous):
    rows, decisions = apply_smart_ids([incoming], previous, "person_id")
    assert rows[0]["person_id"] is None
    assert decisions[0]["outcome"] == "unresolved"
    assert decisions[0]["candidate_ids"] == []


@pytest.mark.parametrize(
    ("skus", "strings", "group", "expected", "outcome"),
    [
        ([42], True, None, 17, "exact"),
        ([42, 42], False, "site", 17, "exact"),
        ([42, 43], False, "site", None, "ambiguous"),
        ([42, 99], False, "site", None, "unresolved"),
    ],
)
async def test_smartid_uses_accepted_values_and_consistent_contributors(
    tmp_path, skus, strings, group, expected, outcome
):
    source = tmp_path / "inventory.json"
    source.write_text(
        json.dumps(
            [
                {"sku": sku, "site": "Same warehouse", "amount": i}
                for i, sku in enumerate(skus, start=1)
            ]
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "parts.json"
    reference.write_text(
        '[{"id":17,"sku":42},{"id":18,"sku":43},{"id":19,"sku":"42"}]', encoding="utf-8"
    )
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        dataset_local_roots=[str(tmp_path)],
        search_provider="disabled",
    )
    result = await arun(
        goal="Prepare warehouse inventory",
        schema=SCHEMA,
        task={
            "dataset_sources": [{"url": source.as_uri(), "format": "json"}],
            "target_records": len(skus),
        },
        groupby=group,
        smartid=reference,
        export=tmp_path / "inventory-output.json",
        config=config,
    )
    assert result.completed
    if strings:
        # A saved display preference can outlive the original column shorthand
        # when a proposal replaces its schema. Keep the typed ledger evidence.
        with closing(ResearchStore(config.sqlite_db_path)) as store:
            options = store.events(result.run_id, "product_options")[-1]["payload"]
            store.event(result.run_id, "product_options", {**options, "strings": True})
        result = await arun(resume=result.run_id, config=config)
    (row,) = result.records
    assert row["part_id"] == expected
    if strings:
        assert row["sku"] == "42"
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        event = store.events(result.run_id, "smartid")[-1]
        (decision,) = event["payload"]["decisions"]
        assert decision["outcome"] == outcome
        assert decision["matched_id"] == row["part_id"]
        (binding,) = store.events(result.run_id, "smartid_reference")
        assert binding["payload"] == event["payload"]["reference_binding"]


@pytest.mark.parametrize("alias", [False, True])
async def test_bad_reference_stops_before_creating_a_run(tmp_path, monkeypatch, alias):
    reference = tmp_path / "reference.json"
    reference.write_text('[{"id":1},{"id":1}]', encoding="utf-8")
    database = reference if alias else tmp_path / "new.db"
    search = AsyncMock(side_effect=AssertionError("An invalid reference cannot start a search"))
    monkeypatch.setattr("verboisy.api.web_search", search)
    with pytest.raises(VerboisyError, match="duplicate ids|database paths"):
        await arun(
            goal="Find parts",
            schema=SCHEMA,
            smartid=reference,
            config=Settings(_env_file=None, sqlite_db_path=str(database)),
        )
    search.assert_not_called()
    assert not (tmp_path / "new.db").exists()
    assert reference.read_text(encoding="utf-8") == '[{"id":1},{"id":1}]'


async def test_paused_run_checks_pinned_reference_before_accepting_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reference = Path("parts.json")
    reference.write_text('[{"id":17,"sku":42}]', encoding="utf-8")
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), search_provider="disabled"
    )
    with pytest.raises(SearchUnavailableError) as stopped:
        await arun(goal="Find parts", schema=SCHEMA, smartid=reference, config=config)
    run_id = stopped.value.details["run_id"]
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        assert len(store.events(run_id, "smartid_reference")) == 1
        assert not store.events(run_id, "smartid")
        proposed = propose_change(
            store,
            run_id,
            {
                "description": "Use the warehouse catalogue",
                "goal": "Find parts in the catalogue",
                "schema": SCHEMA,
                "task": {"seed_urls": ["https://example.test/catalogue"]},
            },
        )
        saved = store.load(run_id)
        events = store.events(run_id)
    reference.write_text('[{"id":99,"sku":42}]', encoding="utf-8")
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with pytest.raises(VerboisyError, match="SmartID reference changed"):
        await arun(okresume=run_id, config=config)
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert store.load(run_id) == saved
        assert pending_change(store, run_id) == proposed
        assert store.events(run_id) == events
