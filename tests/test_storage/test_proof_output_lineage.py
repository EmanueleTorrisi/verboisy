# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Proof headings distinguish exported rows from contributing evidence."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


@pytest.mark.parametrize("grouped", [False, True])
async def test_proof_uses_exact_manifest_mapping_and_internal_evidence_ids(tmp_path, grouped):
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons", name="Alba")
        accept_observation(store, rid, task, "persons", name="Beta", revision="second")
        ids = [row["record_id"] for row in store.evidence(rid)]
        options = {"proof": True, "order": [{"field": "name", "direction": "desc"}]}
        if grouped:
            options["groupby"] = "population"
        store.event(rid, "product_options", options)
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
    destination = tmp_path / "rows.json"
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
            report = (tmp_path / "rows.proof.txt").read_text()
            manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
            headings = [line for line in report.splitlines() if line.startswith("Output record ")]
            assert headings == ["Output record " + str(row["id"]) for row in result.records]
            for mapping in manifest["output_lineage"]:
                contributors = mapping.get("record_ids", [mapping.get("record_id")])
                start = report.index("\nOutput record " + str(mapping["output_id"]) + "\n")
                section = report[start:].split("\n\n", 1)[0]
                for contributor in contributors:
                    assert "Contributor evidence: " + contributor in section
            for internal_id in ids:
                assert "\nEvidence record " + internal_id + "\n" in report
            assert "\nRecord 2\n" not in report
            assert "\nRecord 1\n" not in report
        model.assert_not_awaited()
        browser.assert_not_awaited()


async def test_empty_api_proof_has_no_output_or_evidence_headings(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    await arun(
        resume=rid,
        config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "replay.db")),
        export=tmp_path / "empty.json",
        proof=True,
    )
    report = (tmp_path / "empty.proof.txt").read_text()
    assert "Exported rows and evidence contributors" in report
    assert "No accepted records were persisted." in report
    assert "\nOutput record " not in report
