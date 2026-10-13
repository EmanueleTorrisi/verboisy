# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public runs reject source, configuration and reference aliases before writing."""

import json
from contextlib import closing
from pathlib import Path

import pytest
from verboisy import arun
from verboisy.api import _export_paths
from verboisy.storage.path_safety import dataset_output_paths
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


def inputs(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('[{"name":"Alice"}]')
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        )
    )
    reference = tmp_path / "previous.json"
    reference.write_text('[{"id":1,"name":"Alice"}]')
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        dataset_local_roots=[str(tmp_path)],
        search_provider="disabled",
    )
    return source, schema, reference, config


@pytest.mark.parametrize("which", ["source", "schema", "reference"])
@pytest.mark.parametrize("index", range(6))
async def test_all_sidecars_reject_hardlinks_to_each_input(tmp_path, which, index):
    source, schema, reference, config = inputs(tmp_path)
    protected = {"source": source, "schema": schema, "reference": reference}[which]
    original = protected.read_bytes()
    output = tmp_path / "rows.json"
    dataset_output_paths(output)[index].hardlink_to(protected)
    with pytest.raises(VerboisyError):
        await arun(
            goal="Names",
            schema=schema,
            smartid=reference,
            dataset_sources=[{"format": "json", "url": source.as_uri()}],
            export=output,
            config=config,
        )
    assert protected.read_bytes() == original
    if (tmp_path / "run.db").exists():
        with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
            assert store.db.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0


async def test_saved_configuration_and_reference_protection_on_resume(tmp_path):
    source, schema, reference, config = inputs(tmp_path)
    result = await arun(
        goal="Names",
        schema=schema,
        smartid=reference,
        dataset_sources=[{"format": "json", "url": source.as_uri()}],
        config=config,
    )
    for protected in (source, schema, reference):
        output = tmp_path / "alias.json"
        output.hardlink_to(protected)
        original = protected.read_bytes()
        with pytest.raises(VerboisyError):
            await arun(resume=result.run_id, export=output, config=config)
        assert protected.read_bytes() == original
        output.unlink()


@pytest.mark.parametrize("parameter", ["task", "dataset_projection"])
async def test_bracketed_configuration_filenames_are_protected(tmp_path, parameter):
    source, _schema, _reference, config = inputs(tmp_path)
    configuration = tmp_path / f"[{parameter}].json"
    configuration.write_text("{}")
    with pytest.raises(VerboisyError, match="differ"):
        await arun(
            goal="Names",
            schema=["name"],
            dataset_sources=[{"format": "json", "url": source.as_uri()}],
            export=configuration,
            config=config,
            **{parameter: str(configuration)},
        )
    assert configuration.read_text() == "{}"


async def test_schema_path_protection_matches_loader_whitespace_handling(tmp_path):
    source, schema, _reference, config = inputs(tmp_path)
    original = schema.read_bytes()
    with pytest.raises(VerboisyError, match="differ"):
        await arun(
            goal="Names",
            schema="  " + str(schema) + "  ",
            dataset_sources=[{"format": "json", "url": source.as_uri()}],
            export=schema,
            config=config,
        )
    assert schema.read_bytes() == original


async def test_direct_exports_protect_stored_sources_despite_task_override(tmp_path):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.dataset import export_dataset
    from verboisy.storage.proof import export_proof

    source, schema, _reference, config = inputs(tmp_path)
    result = await arun(
        goal="Names",
        schema=schema,
        dataset_sources=[{"format": "json", "url": source.as_uri()}],
        config=config,
    )
    original = source.read_bytes()
    with closing(ResearchStore(config.sqlite_db_path)) as store:
        # A caller may choose CSV presentation independently; that must not erase
        # the stored acquisition contract's input protections.
        with pytest.raises(ValueError):
            export_dataset(store, result.run_id, source, json.loads(schema.read_text()), TaskSpec())
        destination = tmp_path / "proof.json"
        proof = tmp_path / "proof.proof.txt"
        proof.hardlink_to(source)
        with pytest.raises(ValueError):
            export_proof(store, result.run_id, destination)
    assert source.read_bytes() == original


def test_export_validator_rejects_symlink_database_hardlink_and_cross_bundle_alias(tmp_path):
    source = tmp_path / "source.json"
    source.touch()
    output = tmp_path / "alias.json"
    output.symlink_to(source)
    with pytest.raises(VerboisyError, match="symlink"):
        _export_paths(output, str(tmp_path / "run.db"))
    output.unlink()
    output.hardlink_to(source)
    with pytest.raises(VerboisyError):
        _export_paths(output, str(source))
    output.unlink()
    first = tmp_path / "first.json"
    first.touch()
    output.hardlink_to(first)
    with pytest.raises(VerboisyError):
        _export_paths([first, output], str(tmp_path / "run.db"))


async def test_export_rechecks_inputs_after_research(tmp_path, monkeypatch):
    source, schema, reference, config = inputs(tmp_path)
    output = tmp_path / "rows.json"
    from verboisy.output import write_output

    def alias_before_publish(*args, **kwargs):
        output.hardlink_to(source)
        return write_output(*args, **kwargs)

    monkeypatch.setattr("verboisy.api.write_output", alias_before_publish)
    with pytest.raises(VerboisyError):
        await arun(
            goal="Names",
            schema=schema,
            smartid=reference,
            dataset_sources=[{"format": "json", "url": source.as_uri()}],
            export=output,
            config=config,
        )
    assert source.read_text() == '[{"name":"Alice"}]'


async def test_publication_io_failure_retains_reexportable_run(tmp_path, monkeypatch):
    source, schema, _reference, config = inputs(tmp_path)
    output = tmp_path / "rows.json"
    original_replace = Path.replace

    def fail_destination(path, target):
        if Path(target) == output:
            raise PermissionError("destination temporarily unwritable")
        return original_replace(path, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "replace", fail_destination)
        with pytest.raises(VerboisyError, match="run .* is saved"):
            await arun(
                goal="Names",
                schema=schema,
                dataset_sources=[{"format": "json", "url": source.as_uri()}],
                export=output,
                config=config,
            )
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        rid = store.load(None)["id"]
        assert len(store.records(rid)) == 1
    source.unlink()
    resumed = await arun(resume=rid, config=config)
    assert len(resumed.records) == 1 and json.loads(output.read_text())[0]["name"] == "Alice"
