# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Distribution extraction rejects escaping, duplicate and ambiguous members."""

import importlib.util
import sys
import tomllib
import zipfile
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


@pytest.mark.parametrize(
    "expression,legacy_terms,valid",
    [
        ("LicenseRef-Verboisy-Source-Inspection-2.0", False, True),
        ("LicenseRef-Verboisy-Source-Inspection-1.0", False, False),
        ("LicenseRef-Verboisy-Source-Inspection-2.0", True, False),
    ],
)
def test_distribution_license_matches_current_project_and_terms(
    tmp_path, expression, legacy_terms, valid
):
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    wheel = tmp_path / "verboisy-1.0.0-py3-none-any.whl"
    terms = (root / "LICENSE").read_bytes()
    if legacy_terms:
        terms = terms.replace(b"LICENSE 2.0", b"LICENSE 1.0")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "verboisy-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: verboisy\nVersion: 1.0.0\n"
            "Requires-Python: >=3.11,<3.15\nLicense-Expression: " + expression + "\n\n",
        )
        archive.writestr(
            "verboisy-1.0.0.dist-info/entry_points.txt",
            "[console_scripts]\nverboisy = verboisy.cli.main:app\n",
        )
        archive.writestr("verboisy-1.0.0.dist-info/licenses/LICENSE", terms)
        for name in ("__init__.py", "api.py", "py.typed"):
            archive.write(root / "src/verboisy" / name, "verboisy/" + name)
    if valid:
        assert module.inspect_archive(wheel)["license"] == project["license"]
    else:
        with pytest.raises(ValueError, match="metadata|license"):
            module.inspect_archive(wheel)


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
