# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read-only repository consistency checks, separate from release qualification.

The checker does not inspect secrets, Git history or external services. A passing
result says the reviewed local contracts are consistent, not that the product has
passed its pending acceptance, platform or legal gates.
"""

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote


def inspect(root: Path) -> dict[str, object]:
    issues: list[str] = []
    root = root.resolve()
    source = root / "src/verboisy"
    modules = sorted(source.rglob("*.py"))
    documents = sorted(
        {
            root / "README.md",
            root / "ARCHITECTURE.md",
            *root.glob("docs/*.md"),
            *root.glob(".github/readme/*.md"),
        }
    )
    for path in modules:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(root).as_posix()
        if "Copyright (c) 2026 Emanuele Torrisi" not in "\n".join(text.splitlines()[:8]):
            issues.append(f"Missing source copyright header: {name}")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            issues.append(f"Invalid Python source: {name}")
            continue
        if not ast.get_docstring(tree):
            issues.append(f"Missing module responsibility documentation: {name}")
    if not modules:
        issues.append("No production Python modules found")
    for path in documents:
        if not path.is_file():
            issues.append(f"Missing document: {path.relative_to(root)}")
            continue
        # Code examples are not document navigation. Ignore their Markdown-like
        # literals, then check actual relative destinations without making requests.
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for raw in re.findall(r"\]\(([^)]+)\)", text):
            target = raw.split("#", 1)[0]
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            resolved = path.parent / unquote(target)
            if not resolved.exists():
                issues.append(f"Broken local link in {path.relative_to(root)}: {target}")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    tree = ast.parse((source / "__init__.py").read_text())
    versions = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets)
    ]
    if versions != [project["project"]["version"]]:
        issues.append("Package version and public __version__ differ")
    if project["project"].get("license") != "BSD-2-Clause" or not (root / "LICENSE").is_file():
        issues.append("Current distribution terms require an explicit reviewed metadata change")
    matrix = json.loads((root / "evals/release-matrix.json").read_text())
    if [gate["id"] for gate in matrix["gates"]] != list(range(1, 8)):
        issues.append("Release matrix must retain all seven gates")
    if (root / "ARCHITECTURE.md").read_bytes() != (root / "docs/architecture.md").read_bytes():
        issues.append("Architecture entry points disagree")
    publish = (root / ".github/workflows/publish.yml").read_text()
    if (
        "if: vars.RELEASE_ENABLED == 'true' && github.event.repository.private == false"
        not in publish
    ):
        issues.append("Reviewed private-release publication guard is missing")
    pages = (root / ".github/workflows/docs.yml").read_text()
    if "vars.PAGES_ENABLED == 'true' && github.event.repository.private == false" not in pages:
        issues.append("Reviewed private documentation publication guard is missing")
    plan = json.loads((root / "evals/batch6-commits.json").read_text())["entries"]
    paths = [entry["path"] for entry in plan]
    messages = [entry["message"] for entry in plan]
    if not paths or len(set(paths)) != len(paths) or len(set(messages)) != len(messages):
        issues.append("Commit plan must contain distinct files and distinct messages")
    if any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
        issues.append("Commit plan paths must stay inside the repository")
    if any(not isinstance(message, str) or not message.strip() for message in messages):
        issues.append("Commit subjects must be nonempty professional descriptions")
    return {
        "inspection_version": "1",
        "scope": "local_repository_consistency",
        "passed": not issues,
        "source_modules": len(modules),
        "documents": len(documents),
        "issues": issues,
        "production_status": matrix["production_status"],
        "release_gates": matrix["gates"],
        "legal_review_performed": False,
        "live_or_platform_qualification_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="Print the complete structured report")
    args = parser.parse_args()
    try:
        report = inspect(args.repo)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError) as error:
        print(f"Repository check failed: {type(error).__name__}")
        return 1
    print(
        json.dumps(report, indent=2)
        if args.json
        else (
            f"Repository consistency: {'passed' if report['passed'] else 'failed'}; "
            f"production: {report['production_status']}"
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
