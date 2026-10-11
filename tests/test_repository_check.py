# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Repository checks distinguish broken local contracts from pending qualification."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "repository_check", ROOT / "scripts/check_repository.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.fixture
def repo(tmp_path):
    for name in ("src", "docs", ".github", "evals"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in (
        "README.md",
        "ARCHITECTURE.md",
        "LICENSE",
        "logo.png",
        "pyproject.toml",
        "Makefile",
        "CHANGELOG.md",
        "COPYRIGHT.md",
    ):
        shutil.copyfile(ROOT / name, tmp_path / name)
    # Relative docs can legitimately reference test fixtures and script files.
    for name in ("tests", "scripts", "native", "docker", "examples", "benchmarks"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "mkdocs.yml", tmp_path / "mkdocs.yml")
    return tmp_path


def test_actual_repository_consistency_is_not_product_certification():
    result = CHECK.inspect(ROOT)
    assert result["passed"], result["issues"]
    assert result["production_status"] == "not_certified"
    assert result["legal_review_performed"] is False


@pytest.mark.parametrize(
    "case",
    [
        "header",
        "docstring",
        "syntax",
        "link",
        "version",
        "license",
        "gates",
        "architecture",
        "publish",
        "pages",
    ],
)
def test_repository_tampering_is_reported(repo, case):
    if case in {"header", "docstring", "syntax"}:
        path = repo / "src/verboisy/llm/__init__.py"
        text = path.read_text()
        if case == "header":
            text = text.replace("Copyright (c) 2026 Emanuele Torrisi", "Removed")
        elif case == "docstring":
            text = "\n".join(line for line in text.splitlines() if not line.startswith('"""'))
        else:
            text += "\ninvalid Python !\n"
        path.write_text(text)
    elif case == "link":
        (repo / "README.md").write_text("[Missing](missing.md)")
    elif case in {"version", "license"}:
        path = repo / "pyproject.toml"
        path.write_text(
            path.read_text().replace('version = "1.0.0"', 'version = "9.9.9"')
            if case == "version"
            else path.read_text().replace('license = "BSD-2-Clause"', 'license = "Unreviewed"')
        )
    elif case == "gates":
        path = repo / "evals/release-matrix.json"
        value = json.loads(path.read_text())
        value["gates"].pop()
        path.write_text(json.dumps(value))
    elif case == "architecture":
        (repo / "docs/architecture.md").write_text("Diverged")
    else:
        (repo / f".github/workflows/{'publish' if case == 'publish' else 'docs'}.yml").write_text(
            "unguarded"
        )
    assert CHECK.inspect(repo)["passed"] is False


def test_missing_repository_cli_fails_without_traceback(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_repository.py"), "--repo", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and "Traceback" not in result.stderr


@pytest.mark.parametrize("case", ["duplicate", "outside", "empty"])
def test_commit_plan_does_not_accept_unsafe_or_generic_empty_entries(repo, case):
    path = repo / "evals/batch6-commits.json"
    plan = json.loads(path.read_text())
    if case == "duplicate":
        plan["entries"].append(plan["entries"][0])
    elif case == "outside":
        plan["entries"][0]["path"] = "../private"
    else:
        plan["entries"][0]["message"] = " "
    path.write_text(json.dumps(plan))
    assert CHECK.inspect(repo)["passed"] is False
