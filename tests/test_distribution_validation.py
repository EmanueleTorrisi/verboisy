# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Distribution extraction rejects escaping, duplicate and ambiguous members."""

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "distribution", Path(__file__).resolve().parents[1] / "scripts/check_distribution.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "names", [["../file"], ["/file"], ["C:/file"], ["a\\b"], ["a", "a"], ["a/./b", "a/b"]]
)
def test_unsafe_distribution_paths(names):
    with pytest.raises(ValueError):
        module.safe_members(names)


def test_safe_distribution_paths():
    module.safe_members(["verboisy-1.0.0/", "verboisy-1.0.0/src/verboisy/api.py"])


@pytest.mark.parametrize("wheel_count", [0, 2])
def test_distribution_cli_identifies_artifact_count_failure(
    tmp_path, monkeypatch, capsys, wheel_count
):
    for index in range(wheel_count):
        (tmp_path / f"artifact-{index}.whl").write_bytes(b"unused fixture")
    monkeypatch.setattr(sys, "argv", ["check_distribution.py", "--dist-dir", str(tmp_path)])
    assert module.main() == 1
    error = capsys.readouterr().err
    assert "locating artifacts" in error
    assert f"found {wheel_count} wheels and 0 sdists" in error
    assert "fresh output directory" in error
