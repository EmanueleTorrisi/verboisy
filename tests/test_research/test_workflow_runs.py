# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Execute and resume workflow-defined runs through the real local ingestion path."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from verboisy import run
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError
from verboisy.workflows import WorkflowError


@pytest.fixture(autouse=True)
def no_external_services(monkeypatch):
    fail = AsyncMock(side_effect=AssertionError("Unexpected external operation"))
    monkeypatch.setattr("verboisy.llm.client.LLMClient.complete_json", fail)
    monkeypatch.setattr("verboisy.api.web_search", fail)
    monkeypatch.setattr("verboisy.browser.context.BrowserManager.start", fail)


@pytest.fixture
def configured(tmp_path):
    grant = tmp_path / "granted"
    grant.mkdir()
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "research.db"),
        dataset_local_roots=[str(grant)],
        model_request_budget=1,
        search_request_budget=0,
        search_provider="disabled",
        browser_auto_install=False,
    )
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "available": {"type": "boolean"}},
        "required": ["name", "available"],
        "additionalProperties": False,
    }
    definition = {
        "version": "1",
        "name": "catalog",
        "revision": 3,
        "goal": "Prepare supplied catalog values.",
        "schema": schema,
        "task": {
            "dataset_sources": [{"format": "jsonl", "url": "input:catalog"}],
            "target_records": 1,
        },
    }
    recipe = tmp_path / "catalog.json"
    recipe.write_bytes(json.dumps(definition).encode())
    source = grant / "catalog.jsonl"
    source.write_bytes(b'{"name":"original","available":false}\n')
    return config, recipe, source, definition


def read_json(path):
    return json.loads(path.read_bytes())


def test_reuse_and_resume_preserve_the_exact_workflow_origin(tmp_path, configured):
    config, recipe, source, definition = configured
    digest = hashlib.sha256(recipe.read_bytes()).hexdigest()
    first = tmp_path / "first.json"
    args = {"config": config, "workflow": recipe, "workflow_sha256": digest}
    original = run(**args, workflow_inputs={"catalog": source}, export=first, proof=True)
    assert original.completed and read_json(first)[0]["available"] is False
    origin = {"version": "1", "name": "catalog", "revision": 3, "sha256": digest}
    manifest = read_json(original.manifest_path)
    assert manifest["workflow_origin"] == origin
    assert manifest["model_request_units"] == 0
    journal = read_json(first.with_suffix(".json.events.json"))["events"]
    assert [e["payload"] for e in journal if e["kind"] == "workflow_origin"] == [origin]
    protected = next(e["payload"]["paths"] for e in journal if e["kind"] == "export_inputs")
    assert {str(recipe.resolve()), str(source.resolve())} <= set(protected)

    replacement = source.with_name("new=version.jsonl")
    replacement.write_bytes(b'{"name":"replacement","available":true}\n')
    second = tmp_path / "second.json"
    repeated = run(**args, workflow_inputs={"catalog": replacement}, export=second)
    assert repeated.completed and repeated.run_id != original.run_id
    assert read_json(second)[0]["name"] == "replacement"
    assert read_json(repeated.manifest_path)["workflow_origin"] == origin

    recipe.write_bytes(json.dumps(dict(definition, revision=4, goal="Changed")).encode())
    source.unlink()
    with pytest.raises(WorkflowError, match="differs"):
        run(**args, workflow_inputs={"catalog": replacement})
    reexport = tmp_path / "resumed.json"
    resumed = run(resume=original.run_id, config=config, export=reexport)
    assert resumed.completed and read_json(reexport) == read_json(first)
    assert read_json(resumed.manifest_path)["workflow_origin"] == origin


@pytest.mark.parametrize(
    "options",
    [
        {"goal": "different goal"},
        {"schema": ["other"]},
        {"task": {}},
        {"dataset_sources": []},
        {"identity": ["/different"]},
        {"maxrows": 9},
        {"include": ["example.test"]},
        {"research": True},
        {"resume": True},
        {"okresume": "run"},
    ],
)
def test_workflows_cannot_override_run_definition_or_resume(configured, options):
    config, recipe, _, _ = configured
    recipe.unlink()
    with pytest.raises(WorkflowError, match="supplies the goal"):
        run(config=config, workflow=recipe, **options)
    assert not config_db(config).exists()


def config_db(config):
    return Path(config.sqlite_db_path)


def test_binding_or_pin_without_workflow_is_rejected(configured):
    config, _, source, _ = configured
    for options in ({"workflow_inputs": {"catalog": source}}, {"workflow_sha256": "a" * 64}):
        with pytest.raises(WorkflowError, match="require a workflow"):
            run(config=config, **options)
    assert not config_db(config).exists()


def test_recipe_and_inputs_are_protected_before_run_and_on_resume(tmp_path, configured):
    config, recipe, source, _ = configured
    original_recipe = recipe.read_bytes()
    inputs = {"workflow": recipe, "workflow_inputs": {"catalog": source}}
    aliased_db = config.model_copy(update={"sqlite_db_path": str(source)})
    with pytest.raises(WorkflowError, match="database paths"):
        run(**inputs, config=aliased_db)
    assert source.read_bytes() == b'{"name":"original","available":false}\n'
    with pytest.raises(VerboisyError, match="Export files must differ"):
        run(**inputs, config=config, export=recipe)
    assert recipe.read_bytes() == original_recipe and not config_db(config).exists()
    finished = run(**inputs, config=config, export=tmp_path / "result.json")
    assert finished.completed
    with pytest.raises(VerboisyError, match="Export destination aliases an input"):
        run(config=config, resume=finished.run_id, export=recipe)
    assert recipe.read_bytes() == original_recipe


def test_workflow_bindings_do_not_grant_access_to_local_data(tmp_path, configured):
    config, recipe, _, _ = configured
    denied = tmp_path / "outside.jsonl"
    denied.write_bytes(b'{"name":"outside","available":false}\n')
    result = run(workflow=recipe, workflow_inputs={"catalog": denied}, config=config)
    assert not result.completed and result.stop_reason == "dataset_source_failure"
    assert not result.records


def test_ambiguous_saved_origin_blocks_resume_and_preserves_exports(tmp_path, configured):
    config, recipe, source, _ = configured
    output = tmp_path / "result.json"
    result = run(config=config, workflow=recipe, workflow_inputs={"catalog": source}, export=output)
    original = result.manifest_path.read_bytes()
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        state = store.load(result.run_id)
        schema = json.loads(state["schema_json"])
        task = TaskSpec.model_validate_json(state["task_json"])
        store.event(result.run_id, "workflow_origin", {})
        with pytest.raises(WorkflowError, match="ambiguous"):
            export_dataset(store, result.run_id, output, schema, task)
    with pytest.raises(WorkflowError, match="ambiguous"):
        run(config=config, resume=result.run_id, export=output)
    assert result.manifest_path.read_bytes() == original


def test_output_metadata_cannot_invent_a_workflow_origin(tmp_path, configured):
    config, _, source, definition = configured
    result = run(
        config=config,
        goal=definition["goal"],
        schema=definition["schema"],
        task={
            "dataset_sources": [{"format": "jsonl", "url": source.as_uri()}],
            "target_records": 1,
        },
    )
    assert result.completed
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        state = store.load(result.run_id)
        manifest = export_dataset(
            store,
            result.run_id,
            tmp_path / "export.json",
            json.loads(state["schema_json"]),
            TaskSpec.model_validate_json(state["task_json"]),
            metadata={"tag": "custom", "workflow_origin": {"name": "forged"}},
        )
    info = read_json(manifest)
    assert info["tag"] == "custom" and "workflow_origin" not in info


def test_workflow_creation_rolls_back_if_origin_cannot_be_saved(configured):
    config, recipe, source, _ = configured
    with closing(ResearchStore(config.sqlite_db_path)) as store, store.db:
        store.db.execute(
            "CREATE TRIGGER reject_origin BEFORE INSERT ON events "
            "WHEN NEW.kind='workflow_origin' BEGIN SELECT RAISE(ABORT, 'fixture'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture"):
        run(config=config, workflow=recipe, workflow_inputs={"catalog": source})
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        assert store.db.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
