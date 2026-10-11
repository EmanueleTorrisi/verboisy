# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Portable scalar chains match normalized and string output without mutating evidence."""

import json

import pytest
from verboisy import arun
from verboisy.storage.dataset import export_dataset
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import (
    SCHEMA,
    accept_observation,
    bound_event,
    ledger,
)


@pytest.mark.parametrize("normalized", [False, True])
@pytest.mark.parametrize("strings", [False, True])
async def test_scalar_api_chain_reconstructs_output_after_resume(tmp_path, normalized, strings):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(
            store, rid, task, "thousands of persons" if normalized else "persons"
        )
        if normalized:
            store.event(rid, "unit_normalization", bound_event(store, rid, record_id))
        evidence = store.evidence(rid)
        store.event(rid, "product_options", {"strings": strings})
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    destination = tmp_path / "rows.json"
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
    for _ in range(2):
        result = await arun(resume=rid, config=config, export=destination)
        manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
        cells = manifest["cell_lineage"]
        cell = next(cell for cell in cells if cell["pointer"] == "/population")
        assert cell["status"] == "resolved"
        assert cell["record_id"] == record_id
        assert cell["snapshot_id"] == evidence[0]["snapshot"]["id"]
        assert cell["raw_value"] == 2
        assert cell["output_value"] == result.records[0]["population"]
        expected = (
            ["literal_evidence"]
            + (["unit_normalization"] if normalized else [])
            + (["string_conversion"] if strings else [])
        )
        assert [step["operation"] for step in cell["steps"]] == expected
        replayed = cell["steps"][0]["value"]
        for step in cell["steps"][1:]:
            assert json.dumps(step["input"]) == json.dumps(replayed)
            assert step["input"] == replayed
            replayed = step["output"]
        assert json.dumps(replayed) == json.dumps(cell["output_value"])
        assert replayed == cell["output_value"]
        assert json.loads(destination.with_suffix(".json.evidence.json").read_text()) == evidence


@pytest.mark.parametrize("case", ["new_field", "changed_value", "grouped"])
def test_unsupported_cell_derivation_remains_unresolved(tmp_path, case):
    with ledger(tmp_path) as (store, rid, task):
        record_id = accept_observation(store, rid, task, "persons")
        row = store.records(rid)[0]
        pointer = "/population"
        mapping = {"output_id": row["id"], "record_id": record_id}
        if case == "new_field":
            row["new_field"] = "invented"
            pointer = "/new_field"
        elif case == "changed_value":
            row["population"] = 999
        else:
            mapping = {"output_id": row["id"], "record_ids": [record_id]}
        path = export_dataset(
            store, rid, tmp_path / "rows.json", SCHEMA, task, rows=[row], output_lineage=[mapping]
        )
        cells = json.loads(path.read_text())["cell_lineage"]
        assert next(cell for cell in cells if cell["pointer"] == pointer)["status"] == "unresolved"
