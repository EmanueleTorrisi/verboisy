# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Atomic publication flushes content before rename and syncs directory boundaries."""

import errno
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from verboisy.storage import exporters


def test_publication_sync_follows_replace(tmp_path, monkeypatch):
    destination = tmp_path / "rows.json"
    observed = []
    original = exporters.sync_directory

    def sync(path):
        assert destination.read_text() == "[]\n"
        observed.append(path)
        return original(path)

    monkeypatch.setattr(exporters, "sync_directory", sync)
    exporters.DataExporter.export_json([], destination)
    assert observed == [tmp_path]
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("code", [None, errno.EINVAL, errno.EIO])
def test_directory_sync_only_ignores_unsupported(tmp_path, monkeypatch, code):
    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=0,
        O_DIRECTORY=0,
        open=Mock(return_value=42),
        fsync=Mock(side_effect=OSError(code, "synthetic") if code is not None else None),
        close=Mock(),
    )

    monkeypatch.setattr(exporters, "os", fake_os)

    if code is None:
        assert exporters.sync_directory(tmp_path) is True
    elif code == errno.EINVAL:
        assert exporters.sync_directory(tmp_path) is False
    else:
        with pytest.raises(OSError):
            exporters.sync_directory(tmp_path)

    fake_os.close.assert_called_once_with(42)


def test_platform_without_directory_sync_is_explicit(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(exporters, "os", SimpleNamespace(name="nt"))
    assert exporters.sync_directory(tmp_path) is False


@pytest.mark.parametrize("proof", [False, True])
def test_output_validation_category_and_lower_proof_guard(tmp_path, monkeypatch, proof):
    from contextlib import closing

    import verboisy.output as output
    from verboisy.evidence.models import TaskSpec
    from verboisy.output import PreparedOutput, write_output
    from verboisy.presentation_config import PresentationPreferences
    from verboisy.storage.research import ResearchStore
    from verboisy.utils.exceptions import VerboisyError

    with closing(ResearchStore(tmp_path / "run.db")) as store:
        task = TaskSpec()
        rid = store.create("Synthetic", {"type": "object"}, task, None)
        prepared = PreparedOutput([], [], {}, [], {}, [])

        def invalid(*_args, **_kwargs):
            raise ValueError("integrity")

        monkeypatch.setattr(output, "export_dataset", invalid)
        with pytest.raises(VerboisyError, match="requires|validation") as error:
            write_output(
                store,
                rid,
                prepared,
                () if proof else (tmp_path / "rows.json",),
                {"type": "object"},
                task,
                PresentationPreferences(),
                proof=proof,
                dataset_consistency=None,
            )
        assert "writable" not in str(error.value)
