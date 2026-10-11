# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Completed runs can change presentation without new provider or browser requests."""

import json
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner
from verboisy.api import arun
from verboisy.cli.main import app
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source, TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.presentation import PresentationPreferences, present_rows
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "weight": {"type": "string"},
        "date": {"type": "string", "format": "date"},
    },
}


def saved(tmp_path):
    path = tmp_path / "runs.db"
    store = ResearchStore(str(path))
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("Example measurements", SCHEMA, task, None)
    record = {"name": "Example", "weight": "100 - 120 lb", "date": "2026-10-08"}
    snapshot = Snapshot(
        id="example",
        url="https://example.test/",
        fetched_at="2026-10-08",
        content_hash="fixture",
        truncated=False,
        sources=[Source(id=k, kind="text", text=v, scope="s1") for k, v in record.items()],
    )
    candidate = Candidate(
        scope="s1",
        record=record,
        evidence={"/" + k: Proof(source=k, quote=v) for k, v in record.items()},
    )
    store.queue(rid, snapshot.url, 0, None)
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], snapshot, "fixture")
    store.accept(rid, snapshot, candidate, [], task)
    store.finish(rid, "COMPLETED", "target_met", 17, 796)
    evidence = store.evidence(rid)
    store.close()
    return path, rid, evidence


@pytest.mark.asyncio
async def test_reexport_persists_preferences_and_cell_lineage_without_provider(
    tmp_path, monkeypatch
):
    path, rid, evidence = saved(tmp_path)
    provider = AsyncMock(side_effect=AssertionError("No provider calls during re-export"))
    monkeypatch.setattr(LLMClient, "complete_json", provider)
    output = tmp_path / "rows.json"
    config = Settings(_env_file=None, sqlite_db_path=str(path), search_provider="disabled")
    default = await arun(resume=rid, config=config, export=output)
    assert default.records[0]["weight"] == "45.359237 - 54.431084 kg"
    assert default.records[0]["date"] == "08/10/2026"
    manifest = json.loads(output.with_suffix(".json.manifest.json").read_text())
    assert manifest["presentation_preferences"]["mass_unit"] == "kg"
    assert (
        manifest["collection_schema_valid"] is False
    )  # Display date is not the source ISO contract.
    for cell in manifest["cell_lineage"]:
        assert cell["status"] == "resolved"
        if cell["pointer"] in {"/date", "/weight"}:
            assert cell["steps"][-1]["operation"] == "presentation"
            assert cell["steps"][-1]["output"] == cell["output_value"]
    changed = await arun(
        resume=rid, config=config, mass_unit="lb", date_format="iso", export=output
    )
    assert changed.records[0]["weight"] == "100 - 120 lb"
    assert changed.records[0]["date"] == "2026-10-08"
    again = await arun(resume=rid, config=config, export=output)
    assert again.records == changed.records
    provider.assert_not_called()
    store = ResearchStore(str(path), read_only=True)
    assert store.evidence(rid) == evidence
    assert (store.load(rid)["tokens"], store.load(rid)["reserved"]) == (17, 796)
    assert len(store.events(rid, "presentation_preferences")) == 2
    store.close()


def test_invalid_preference_does_not_create_database(tmp_path):
    import asyncio

    config = Settings(_env_file=None, sqlite_db_path=str(tmp_path / "missing.db"))
    with pytest.raises(VerboisyError, match="Display preferences"):
        asyncio.run(arun(resume="missing", config=config, mass_unit="invalid"))
    assert not (tmp_path / "missing.db").exists()


def test_cli_preferences_forwarded(tmp_path, monkeypatch):
    path, rid, _ = saved(tmp_path)
    monkeypatch.setenv("SQLITE_DB_PATH", str(path))
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--resume",
            rid,
            "--mass-unit",
            "lb",
            "--length-unit",
            "ft",
            "--date-format",
            "mdy",
            "--export",
            str(tmp_path / "cli.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    store = ResearchStore(str(path), read_only=True)
    assert store.events(rid, "presentation_preferences")[-1]["payload"] == {
        "mass_unit": "lb",
        "length_unit": "ft",
        "date_format": "mdy",
    }
    store.close()


def test_grouped_date_presentation_lineage(tmp_path):
    from verboisy.product import transform_rows

    path, rid, _ = saved(tmp_path)
    store = ResearchStore(str(path))
    prefs = PresentationPreferences()
    result = transform_rows(
        store.records(rid), schema_fields=["name", "weight", "date"], groupby="date"
    )
    rows = present_rows(result.rows, SCHEMA, prefs, protected=[])
    mappings = [
        {"output_id": row["id"], "record_ids": result.contributors[row["id"]]} for row in rows
    ]
    manifest_path = export_dataset(
        store,
        rid,
        tmp_path / "group.json",
        SCHEMA,
        TaskSpec(),
        rows=rows,
        metadata={"grouping": {"field": "date"}},
        output_lineage=mappings,
        presentation=prefs,
    )
    cells = json.loads(manifest_path.read_text())["cell_lineage"]
    cell = next(c for c in cells if c["pointer"] == "/date")
    assert cell["status"] == "resolved"
    assert [s["operation"] for s in cell["steps"]] == ["group_key", "presentation"]
    store.close()
