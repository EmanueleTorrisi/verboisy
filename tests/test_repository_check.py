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
        text = path.read_text(encoding="utf-8")
        if case == "header":
            text = text.replace("Copyright (c) 2026 Emanuele Torrisi", "Removed")
        elif case == "docstring":
            text = "\n".join(line for line in text.splitlines() if not line.startswith('"""'))
        else:
            text += "\ninvalid Python !\n"
        path.write_text(text, encoding="utf-8")
    elif case == "link":
        (repo / "README.md").write_text("[Missing](missing.md)", encoding="utf-8")
    elif case in {"version", "license"}:
        path = repo / "pyproject.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "9.9.9"')
            if case == "version"
            else path.read_text(encoding="utf-8").replace(
                'license = "LicenseRef-Verboisy-Source-Inspection-2.0"', 'license = "Unreviewed"'
            ),
            encoding="utf-8",
        )
    elif case == "gates":
        path = repo / "evals/release-matrix.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["gates"].pop()
        path.write_text(json.dumps(value), encoding="utf-8")
    elif case == "architecture":
        (repo / "docs/architecture.md").write_text("Diverged", encoding="utf-8")
    else:
        (repo / f".github/workflows/{'publish' if case == 'publish' else 'docs'}.yml").write_text(
            "unguarded", encoding="utf-8"
        )
    assert CHECK.inspect(repo)["passed"] is False


def test_missing_repository_cli_fails_without_traceback(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_repository.py"), "--repo", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "marker",
    [
        "VERBOISY SOURCE INSPECTION LICENSE 2.0",
        "SPDX-License-Identifier: LicenseRef-Verboisy-Source-Inspection-2.0",
        "Additional rights require a separate written agreement",
        "Third-party libraries, dependencies, vendored packages",
    ],
)
def test_license_scope_and_third_party_notices_cannot_be_silently_removed(repo, marker):
    path = repo / "LICENSE"
    original = path.read_text(encoding="utf-8")

    assert marker in original

    path.write_text(
        original.replace(marker, "Removed"),
        encoding="utf-8",
    )

    assert CHECK.inspect(repo)["passed"] is False


@pytest.mark.parametrize(
    "case", ["example_link", "anchor", "html", "comment_guard", "action", "fingerprint"]
)
def test_expanded_consistency_surfaces(repo, case):
    if case in {"example_link", "anchor", "html"}:
        path = repo / "examples/README.md"
        text = (
            "\n[Missing](absent.md)\n"
            if case == "example_link"
            else "\n[Missing](#not-a-heading)\n"
            if case == "anchor"
            else '\n<a href="absent.md">missing</a>\n'
        )
        path.write_text(path.read_text() + text)
    elif case == "comment_guard":
        path = repo / ".github/workflows/publish.yml"
        text = path.read_text().replace(
            "    if: vars.RELEASE_ENABLED == 'true' && github.event.repository.private == false",
            "    # if: vars.RELEASE_ENABLED == 'true' && github.event.repository.private == false",
        )
        path.write_text(text)
    elif case == "action":
        path = repo / ".github/workflows/docs.yml"
        path.write_text(
            path.read_text().replace(
                "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", "actions/checkout@v6"
            )
        )
    else:
        path = repo / "evals/results/offline-validation.json"
        path.write_text(
            json.dumps(
                {
                    "qualification_applies_to_current_source": True,
                    "source_fingerprints": {"README.md": "0" * 64},
                }
            )
        )
    report = CHECK.inspect(repo)
    assert not report["passed"] and report["documents"] == len(
        [p for p in CHECK.public_files(repo) if p.suffix.lower() == ".md"]
    )


def test_unicode_duplicate_anchors_and_fenced_examples():
    anchors = CHECK.anchors(
        '# Títle\n# Títle\n<a id="explicit"></a>\n```python\n# not a heading\n```\n'
    )
    assert {"títle", "títle-1", "explicit"} <= anchors
    assert "not-a-heading" not in anchors


def test_source_line_ending_attributes(tmp_path):
    # Source ZIPs have no .git directory; exercise the real attributes in a fixture repo.
    shutil.copyfile(ROOT / ".gitattributes", tmp_path / ".gitattributes")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "check-attr",
            "text",
            "eol",
            "--",
            "docker/entrypoint.sh",
            "logo.png",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "docker/entrypoint.sh: eol: lf" in result.stdout
    assert "logo.png: text: unset" in result.stdout


def test_release_disjunction_cannot_weaken_reviewed_guard(repo):
    path = repo / ".github/workflows/publish.yml"
    text = path.read_text().replace(
        "if: vars.RELEASE_ENABLED == 'true' && github.event.repository.private == false",
        "if: vars.RELEASE_ENABLED == 'true' && github.event.repository.private == false || true",
    )
    path.write_text(text)
    assert not CHECK.inspect(repo)["passed"]


def test_code_and_comments_do_not_become_navigation(repo):
    path = repo / "examples/README.md"
    path.write_text(
        path.read_text()
        + "\n`[example](absent.md)`\n<!-- [comment](absent.md) -->\n"
        + '```python\nprint("[sample](absent.md)")\n```\n'
    )
    assert not any("absent.md" in issue for issue in CHECK.inspect(repo)["issues"])


def test_git_inventory_includes_unstaged_patch_additions(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / "README.md").write_text("# Product\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", "README.md", ".gitignore"], check=True)
    added = tmp_path / "new.py"
    added.write_text("value = 1\n")
    generated = tmp_path / "build"
    generated.mkdir()
    (generated / "artifact.py").write_text("generated = True\n")
    assert set(CHECK.public_files(tmp_path)) == {
        tmp_path / ".gitignore",
        tmp_path / "README.md",
        added,
    }
