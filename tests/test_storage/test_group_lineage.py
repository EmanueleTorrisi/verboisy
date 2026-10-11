# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Grouped and sorted output retains every accepted record contributor."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.storage.dataset import export_dataset
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import SCHEMA, accept_observation, ledger


@pytest.mark.parametrize("strings", [False, True])
async def test_grouped_api_resume_maps_contributors_after_sorting(tmp_path, strings):
    with ledger(tmp_path) as (store, rid, task):
        for name, value in [("Alba", 2), ("Beta", 2), ("Gamma", 3)]:
            accept_observation(
                store, rid, task, "persons", name=name, revision=name, population=value
            )
        evidence = store.evidence(rid)
        ids = {row["candidate"]["record"]["name"]: row["record_id"] for row in evidence}
        store.event(
            rid,
            "product_options",
            {
                "strings": strings,
                "groupby": "population",
                "order": [{"field": "population", "direction": "desc"}],
            },
        )
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    destination = tmp_path / "grouped.json"
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
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
            assert len(result.records) == 2
            assert result.records[0]["population"] == ("3" if strings else 3)
            manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
            assert manifest["output_lineage_status"] == "mapped"
            assert manifest["output_lineage"] == [
                {"output_id": 1, "record_ids": [ids["Gamma"]]},
                {"output_id": 2, "record_ids": [ids["Alba"], ids["Beta"]]},
            ]
        model.assert_not_awaited()
        browser.assert_not_awaited()


@pytest.mark.parametrize("invalid", [None, "record", [], ["absent"], [1], "duplicate"])
def test_invalid_group_contributors_rejected_before_export(tmp_path, invalid):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons")
        row = store.records(rid)[0]
        ids = [row["id"], row["id"]] if invalid == "duplicate" else invalid
        destination = tmp_path / "bad.json"
        with pytest.raises(ValueError, match="Invalid output lineage"):
            export_dataset(
                store,
                rid,
                destination,
                SCHEMA,
                task,
                rows=[row],
                output_lineage=[{"output_id": row["id"], "record_ids": ids}],
            )
        assert not destination.exists()
