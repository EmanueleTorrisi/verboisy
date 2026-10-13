# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Destination aliases must fail before a source or provenance file changes."""

from pathlib import Path

import pytest
from verboisy.storage.path_safety import (
    dataset_output_paths,
    export_input_paths,
    local_source_paths,
    protected_run_paths,
    validate_output_paths,
)


@pytest.mark.parametrize("payload", [None, {"smartid": 3}])
def test_malformed_persisted_reference_paths(tmp_path, payload):
    from verboisy.evidence.models import TaskSpec

    with pytest.raises(ValueError):
        protected_run_paths(
            tmp_path / "run.db",
            TaskSpec().model_dump_json(),
            [{"kind": "product_options", "payload": payload}],
        )


def test_persisted_source_and_legacy_reference_paths(tmp_path):
    from verboisy.evidence.models import TaskSpec

    source = tmp_path / "source.json"
    reference = tmp_path / "reference.json"
    task = TaskSpec(dataset_sources=[{"format": "json", "url": source.as_uri()}])
    paths = protected_run_paths(
        tmp_path / "run.db",
        task.model_dump_json(),
        [
            {"kind": "product_options", "payload": {"smartid": str(reference)}},
            {"kind": "product_options", "payload": {}},
        ],
    )
    assert {source, reference, tmp_path / "run.db"} <= paths


@pytest.mark.parametrize("payload", [None, [], {}, {"paths": "relative"}])
def test_malformed_saved_input_payloads(payload):
    with pytest.raises(ValueError, match="journal"):
        export_input_paths([{"kind": "export_inputs", "payload": payload}])


@pytest.mark.parametrize("value", [None, 3, "relative.json"])
def test_malformed_saved_input_path(value):
    with pytest.raises(ValueError, match="absolute"):
        export_input_paths([{"kind": "export_inputs", "payload": {"paths": [value]}}])


def test_saved_input_decoder_skips_unrelated_events(tmp_path):
    assert export_input_paths(
        [
            {"kind": "fixture", "payload": float("nan")},
            {"kind": "export_inputs", "payload": {"paths": [str(tmp_path / "schema.json")]}},
        ]
    ) == {tmp_path / "schema.json"}


def test_local_uri_selection_and_bundle_names(tmp_path):
    source = tmp_path / "source with spaces.json"
    assert local_source_paths([source.as_uri(), "https://example.test/a"]) == (source,)
    outputs = dataset_output_paths(tmp_path / "rows.csv")
    assert len(outputs) == 6 and outputs[-1].name == "rows.proof.txt"


def test_safe_new_existing_and_missing_input_paths(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("original")
    destination = tmp_path / "existing.json"
    destination.write_text("old output")
    validate_output_paths([destination, tmp_path / "new.json"], [source, tmp_path / "missing"])
    assert source.read_text() == "original"


@pytest.mark.parametrize("kind", ["same", "hardlink", "symlink", "directory"])
def test_protected_aliases_and_unsafe_destinations(tmp_path, kind):
    source = tmp_path / "source.json"
    source.write_text("original")
    destination = tmp_path / "output.json"
    if kind == "same":
        destination = source
    elif kind == "hardlink":
        destination.hardlink_to(source)
    elif kind == "symlink":
        destination.symlink_to(source)
    else:
        destination.mkdir()
    with pytest.raises(ValueError):
        validate_output_paths([destination], [source])
    assert source.read_text() == "original"


def test_duplicate_output_and_parent_directory_alias(tmp_path):
    destination = tmp_path / "output.json"
    with pytest.raises(ValueError):
        validate_output_paths([destination, destination], [])
    folder = tmp_path / "folder"
    folder.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(folder, target_is_directory=True)
    with pytest.raises(ValueError):
        validate_output_paths([folder / "output.json"], [alias / "output.json"])


def test_hardlinked_outputs_are_not_separate_artifacts(tmp_path):
    first = tmp_path / "first.json"
    first.touch()
    second = tmp_path / "second.json"
    second.hardlink_to(first)
    with pytest.raises(ValueError, match="inode"):
        validate_output_paths([first, second], [])


def test_stat_errors_propagate(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.touch()
    original = Path.stat

    def fail(path, *args, **kwargs):
        if path == source:
            raise PermissionError("cannot inspect source")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail)
    with pytest.raises(PermissionError):
        validate_output_paths([tmp_path / "output.json"], [source])


def test_settings_retains_custom_dotenv_paths_across_chdir(tmp_path, monkeypatch):
    from verboisy.utils.config import Settings

    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("SEARCH_PROVIDER=disabled\n")
    second.write_text("MAX_STEPS=3\n")
    monkeypatch.chdir(tmp_path)
    config = Settings(_env_file=["first.env", "second.env"])
    assert config.input_files() == (first, second)
    assert config.max_steps == 3
    monkeypatch.chdir(tmp_path.parent)
    assert config.input_files() == (first, second)
    assert Settings(_env_file=None).input_files() == ()


def test_settings_preserves_upstream_positional_and_sentinel_parameters(tmp_path, monkeypatch):
    import inspect

    from pydantic_settings import BaseSettings
    from verboisy.utils.config import Settings

    monkeypatch.chdir(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("MAX_STEPS=3\n")
    parameters = inspect.signature(BaseSettings.__init__).parameters
    index = list(parameters)[1:].index("_env_file")
    positional = Settings(*([None] * index + [dotenv]))
    assert positional.max_steps == 3 and positional.input_files() == (dotenv,)
    sentinel = Settings(_env_file=parameters["_env_file"].default)
    assert sentinel.max_steps == 3 and sentinel.input_files() == (dotenv,)
    equivalent_sentinel = Settings(_env_file=Path())
    assert equivalent_sentinel.max_steps == 3 and equivalent_sentinel.input_files() == (dotenv,)
