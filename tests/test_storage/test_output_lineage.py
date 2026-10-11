# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Sorted public IDs map explicitly to accepted evidence IDs."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.storage.dataset import export_dataset
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


@pytest.mark.parametrize("strings", [False, True])
async def test_completed_api_resume_exports_sorted_lineage_without_external_work(tmp_path, strings):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons", name="Alba")
        accept_observation(store, rid, task, "persons", name="Beta", revision="second")
        ids = {row["candidate"]["record"]["name"]: row["record_id"] for row in store.evidence(rid)}
        store.event(
            rid,
            "product_options",
            {"strings": strings, "order": [{"field": "name", "direction": "desc"}]},
        )
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
    destination = tmp_path / "sorted.json"
    with (
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            AsyncMock(side_effect=AssertionError("unexpected model")),
        ) as model,
        patch(
            "verboisy.browser.context.BrowserManager.start",
            AsyncMock(side_effect=AssertionError("unexpected browser")),
        ) as browser,
    ):
        for _ in range(2):
            result = await arun(resume=rid, config=config, export=destination)
            assert [row["name"] for row in result.records] == ["Beta", "Alba"]
            manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
            assert manifest["output_lineage_status"] == "mapped"
            assert manifest["output_lineage"] == [
                {"output_id": 1, "record_id": ids["Beta"]},
                {"output_id": 2, "record_id": ids["Alba"]},
            ]
        model.assert_not_awaited()
        browser.assert_not_awaited()


@pytest.mark.parametrize("case", ["length", "output_id", "record_id"])
def test_invalid_explicit_mapping_is_rejected_before_export(tmp_path, case):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        row = store.records(rid)[0]
        mapping = [{"output_id": row["id"], "record_id": row["id"]}]
        if case == "length":
            mapping.clear()
        else:
            mapping[0][case] = "absent"
        destination = tmp_path / "bad.json"
        with pytest.raises(ValueError, match="Invalid output lineage"):
            export_dataset(
                store, rid, destination, SCHEMA, task, rows=[row], output_lineage=mapping
            )
        assert not destination.exists()


def test_raw_export_mapping_and_unmapped_shaped_output_are_honest(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        rows = store.records(rid)
        destination = tmp_path / "rows.json"
        path = export_dataset(store, rid, destination, SCHEMA, task)
        assert json.loads(path.read_text())["output_lineage"] == [
            {"output_id": rows[0]["id"], "record_id": rows[0]["id"]}
        ]
        path = export_dataset(
            store,
            rid,
            destination,
            SCHEMA,
            task,
            rows=rows,
            metadata={"output_lineage": [{"record_id": "forged"}]},
        )
        manifest = json.loads(path.read_text())
        assert manifest["output_lineage"] is None
        assert manifest["output_lineage_status"] == "unresolved"
