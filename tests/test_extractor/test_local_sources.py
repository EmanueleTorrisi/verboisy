# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Local capture grants, immutable bytes and controlled failure without network use."""

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from verboisy.extractor.download import DatasetDownloadError
from verboisy.extractor.local import load_local_dataset
from verboisy.utils.config import Settings


@pytest.mark.parametrize(
    "fmt,body",
    [("csv", b"name\nAlice\n"), ("json", b'[{"name":"Alice"}]'), ("jsonl", b'{"name":"Alice"}\n')],
)
async def test_local_file_preserves_bytes_and_uri(tmp_path, monkeypatch, fmt, body):
    file = tmp_path / "people with spaces"
    file.write_bytes(body)
    config = Settings(_env_file=None, dataset_local_roots=[str(tmp_path)])
    network = AsyncMock(side_effect=AssertionError("network"))
    monkeypatch.setattr("verboisy.extractor.download.download_dataset", network)
    captured = await load_local_dataset(file.as_uri(), config, dataset_format=fmt)
    assert captured.dataset.original_bytes == body
    assert captured.dataset.rows[0].values == {"name": "Alice"}
    assert captured.original_url == captured.final_url == file.as_uri()
    assert captured.redirect_chain == (file.as_uri(),)
    assert captured.remote_disposition is None
    network.assert_not_awaited()


@pytest.mark.parametrize(
    "bad",
    [
        "https://example.test/data",
        "file://other-host/data",
        "file:///data?token=secret",
        "file:///data#fragment",
        "file:relative",
        "file:/absolute",
        "file:///has%2fslash",
    ],
)
async def test_noncanonical_or_remote_file_declarations_rejected(tmp_path, bad):
    with pytest.raises(DatasetDownloadError):
        await load_local_dataset(bad, Settings(_env_file=None), dataset_format="csv")


@pytest.mark.parametrize("roots", [[], ["allowed"], ["prefix"]])
async def test_local_source_requires_directory_grant(tmp_path, roots):
    file = tmp_path / "allowed-extra" / "rows.csv"
    file.parent.mkdir()
    file.write_bytes(b"name\nAlice\n")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    root_values = [] if not roots else [str(allowed)]
    with pytest.raises(DatasetDownloadError, match="outside DATASET_LOCAL_ROOTS"):
        await load_local_dataset(
            file.as_uri(),
            Settings(_env_file=None, dataset_local_roots=root_values),
            dataset_format="csv",
        )


async def test_symlink_escape_rejected_before_capture(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"name\nSecret\n")
    link = root / "rows.csv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This platform does not permit creating test symlinks")
    with pytest.raises(DatasetDownloadError, match="outside DATASET_LOCAL_ROOTS"):
        await load_local_dataset(
            link.as_uri(),
            Settings(_env_file=None, dataset_local_roots=[str(root)]),
            dataset_format="csv",
        )


@pytest.mark.parametrize("kind", ["missing", "directory", "root_file", "missing_root", "large"])
async def test_invalid_local_objects_and_limits(tmp_path, kind):
    file = tmp_path / "rows.csv"
    root = str(tmp_path)
    if kind != "missing":
        if kind == "directory":
            file.mkdir()
        else:
            file.write_bytes(b"name\nAlice\n")
    if kind == "root_file":
        root = str(file)
    if kind == "missing_root":
        root = str(tmp_path / "absent")
    with pytest.raises(DatasetDownloadError):
        await load_local_dataset(
            file.as_uri(),
            Settings(_env_file=None, dataset_local_roots=[root]),
            dataset_format="csv",
            max_bytes=3 if kind == "large" else 100,
        )


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
async def test_invalid_local_limits(limit):
    with pytest.raises(ValueError, match="Invalid local"):
        await load_local_dataset(
            "file:///unused", Settings(_env_file=None), dataset_format="csv", max_bytes=limit
        )


@pytest.mark.parametrize("root", ["", "relative"])
def test_local_grants_must_be_absolute(root):
    with pytest.raises(ValidationError, match="absolute paths"):
        Settings(_env_file=None, dataset_local_roots=[root])


@pytest.mark.parametrize("damage", ["identity", "growth", "mtime", "length"])
async def test_changed_opened_object_is_not_captured(tmp_path, monkeypatch, damage):
    file = tmp_path / "rows.csv"
    file.write_bytes(b"name\nAlice\n")
    original = os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        result = original(fd)
        values = list(result)
        calls += 1
        if damage == "identity" and calls == 1:
            values[1] += 1
            return os.stat_result(values)
        if calls == 2:
            if damage == "growth":
                values[6] += 1
            if damage == "mtime":
                values[8] += 1
            if damage == "length":
                values[6] -= 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr("verboisy.extractor.local.os.fstat", changed)
    with pytest.raises(DatasetDownloadError, match="changed"):
        await load_local_dataset(
            file.as_uri(),
            Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
            dataset_format="csv",
        )


async def test_read_limit_enforced_if_file_grows_after_stat(tmp_path, monkeypatch):
    file = tmp_path / "rows.csv"
    file.write_bytes(b"name\nAlice\n")
    original = Path.open

    def grow(path, *args, **kwargs):
        with original(path, "ab") as stream:
            stream.write(b"x" * 100)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow)
    with pytest.raises(DatasetDownloadError, match="byte limit"):
        await load_local_dataset(
            file.as_uri(),
            Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
            dataset_format="csv",
            max_bytes=20,
        )
