# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Grouped cell chains reconstruct keys and arithmetic from accepted contributors."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.core.source_assessment import source_fitness_candidate_key
from verboisy.core.units import canonical_unit, unit_normalization_event
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger


@pytest.mark.parametrize("strings", [False, True])
async def test_group_key_includes_normalized_contributor_chains(tmp_path, strings):
    with ledger(tmp_path) as (store, rid, task):
        for name in ("Alba", "Beta"):
            accept_observation(store, rid, task, "thousands of persons", name=name, revision=name)
            record_id = next(
                row["record_id"]
                for row in store.evidence(rid)
                if row["candidate"]["record"]["name"] == name
            )
            context = next(row for row in store.evidence(rid) if row["record_id"] == record_id)
            store.event(
                rid,
                "unit_normalization",
                unit_normalization_event(
                    record_id=record_id,
                    pointer="/population",
                    original_value=2,
                    unit=canonical_unit("thousands of persons"),
                    candidate_key=source_fitness_candidate_key(
                        Candidate.model_validate(context["candidate"])
                    ),
                    snapshot_id=context["snapshot"]["id"],
                ),
            )
        before = store.evidence(rid)
        store.event(rid, "product_options", {"groupby": "population", "strings": strings})
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "replay.db"), search_provider="disabled"
    )
    with (
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            AsyncMock(side_effect=AssertionError("model")),
        ),
        patch(
            "verboisy.browser.context.BrowserManager.start",
            AsyncMock(side_effect=AssertionError("browser")),
        ),
    ):
        for attempt in range(2):
            destination = tmp_path / f"group-{attempt}.json"
            result = await arun(resume=rid, config=config, export=destination)
            manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
            cell = manifest["cell_lineage"][0]
            assert cell["status"] == "resolved"
            assert cell["steps"][0]["operation"] == "group_key"
            assert cell["steps"][0]["inputs"] == [result.records[0]["population"]] * 2
            for contributor in cell["contributors"]:
                assert contributor["raw_value"] == 2
                assert [step["operation"] for step in contributor["steps"]] == [
                    "literal_evidence",
                    "unit_normalization",
                ] + (["string_conversion"] if strings else [])
            assert json.loads(destination.with_suffix(".json.evidence.json").read_text()) == before


def arithmetic_store(tmp_path):
    store = ResearchStore(str(tmp_path / "arithmetic.db"))
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "region": {"type": "string"},
            "population": {"type": ["number", "null"]},
            "count": {"type": ["integer", "null"]},
        },
    }
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("Fixture", schema, task, None)
    for index, (region, population, count) in enumerate(
        [("A", 2, 3), ("A", 4, None), ("B", None, None)]
    ):
        record = {"name": str(index), "region": region, "population": population, "count": count}
        snapshot = Snapshot(
            id=str(index),
            url=f"https://example.test/{index}",
            fetched_at="2026-10-05T00:00:00Z",
            content_hash=str(index),
            truncated=False,
            sources=[
                Source(id=key, kind="text", text=str(value), scope="entity")
                for key, value in record.items()
            ],
        )
        candidate = Candidate(
            scope="entity",
            record=record,
            evidence={
                f"/{key}": Proof(source=key, quote=str(value), transform="text")
                for key, value in record.items()
            },
        )
        store.queue(rid, snapshot.url, 0, None)
        page = store.next_page(rid)
        store.snapshot(rid, page["id"], snapshot, "fixture")
        store.accept(rid, snapshot, candidate, [], task)
        store.mark_page(page["id"], "done")
    return store, rid, schema, task


async def test_sum_average_nulls_sort_and_resume(tmp_path):
    store, rid, schema, task = arithmetic_store(tmp_path)
    try:
        store.event(
            rid,
            "product_options",
            {"groupby": "region", "order": [{"field": "region", "direction": "desc"}]},
        )
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    finally:
        store.close()
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "arithmetic.db"), search_provider="disabled"
    )
    for attempt in range(2):
        path = tmp_path / f"arithmetic-{attempt}.json"
        result = await arun(resume=rid, config=config, export=path)
        assert result.records == [
            {"id": 1, "region": "B", "population": None, "count": None},
            {"id": 2, "region": "A", "population": 3.0, "count": 3},
        ]
        cells = json.loads(path.with_suffix(".json.manifest.json").read_text())["cell_lineage"]
        assert all(cell["status"] == "resolved" for cell in cells)
        for cell in cells:
            step = cell["steps"][0]
            values = [value for value in step["inputs"] if value is not None]
            if step["operation"] == "sum":
                assert (sum(values) if values else None) == step["output"]
            elif step["operation"] == "average":
                assert (sum(values) / len(values) if values else None) == step["output"]
            else:
                assert all(value == step["output"] for value in step["inputs"])


@pytest.mark.parametrize(
    "case",
    [
        "wrong_value",
        "wrong_members",
        "unknown_group",
        "missing_context",
        "missing_field",
        "bad_grouping",
        "reordered_members",
    ],
)
def test_unverified_group_cell_stays_unresolved(tmp_path, case):
    store, rid, schema, task = arithmetic_store(tmp_path)
    try:
        evidence = store.evidence(rid)
        ids = [row["record_id"] for row in evidence]
        row = {"id": 1, "region": "A", "population": 3.0}
        mapping = {"output_id": 1, "record_ids": ids[:2]}
        metadata = {"grouping": {"field": "region"}}
        if case == "wrong_value":
            row["population"] = 999
        elif case == "wrong_members":
            mapping["record_ids"] = ids
        elif case == "reordered_members":
            mapping["record_ids"] = list(reversed(ids[:2]))
        elif case == "unknown_group":
            metadata["grouping"]["field"] = "absent"
        elif case == "missing_context":
            evidence[0].pop("candidate")
            store.evidence = lambda _: evidence
        elif case == "missing_field":
            row = {"id": 1, "new_field": "unsupported"}
        else:
            metadata["grouping"]["field"] = 12
        path = export_dataset(
            store,
            rid,
            tmp_path / "bad.json",
            schema,
            task,
            rows=[row],
            output_lineage=[mapping],
            metadata=metadata,
        )
        cells = json.loads(path.read_text())["cell_lineage"]
        cell = next(cell for cell in cells if cell["pointer"] != "/region")
        assert cell["status"] == "unresolved"
    finally:
        store.close()


def test_empty_group_export_has_empty_cell_lineage(tmp_path):
    with ledger(tmp_path) as (store, rid, task):
        path = export_dataset(
            store,
            rid,
            tmp_path / "empty.json",
            {"type": "object", "properties": {}},
            task,
            rows=[],
            output_lineage=[],
            metadata={"grouping": {"field": "population"}},
        )
        assert json.loads(path.read_text())["cell_lineage"] == []
