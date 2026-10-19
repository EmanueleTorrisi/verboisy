# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Read-only repository consistency checks, separate from release qualification.

The checker does not inspect secrets, Git history or external services. A passing
result says the reviewed local contracts are consistent, not that the product has
passed real-task acceptance or received a security or legal certification.
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import markdown
import yaml


def public_files(root: Path) -> list[Path]:
    """Include unstaged additions; archive fallback stays in public directories."""
    actual = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, check=False
    )
    is_root = (
        actual.returncode == 0 and Path(actual.stdout.decode().strip()).resolve() == root.resolve()
    )
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
    )
    if is_root and result.returncode == 0:
        return [root / name for name in result.stdout.decode().split("\0") if name]
    candidates = [
        *root.glob("*.md"),
        *root.glob(".github/**/*.md"),
        *root.glob("docs/**/*.md"),
        *root.glob("examples/**/*.md"),
        *root.glob("tests/fixtures/*.md"),
        *root.glob("docker/*.md"),
    ]
    return sorted(set(candidates))


def unfenced(text: str) -> str:
    """Strip backtick/tilde fences before interpreting document navigation."""
    return re.sub(r"(?m)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$", "", text, flags=re.S)


class Destinations(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if value is not None and key in {"href", "src"}:
                self.links.append(value)
            if value is not None and (key == "id" or tag == "a" and key == "name"):
                self.ids.add(value)


def anchors(text: str) -> set[str]:
    """GitHub-style lowercase Unicode headings with duplicate suffixes and HTML IDs."""
    clean = unfenced(text)
    html = Destinations()
    html.feed(clean)
    result = set(html.ids)
    counts: dict[str, int] = {}
    headings = re.findall(r"(?m)^ {0,3}#{1,6} +(.+?)[ \t]*#*[ \t]*$", clean)
    headings += re.findall(r"(?m)^([^\n]+)\n {0,3}(?:=+|-+)[ \t]*$", clean)
    for heading in headings:
        heading = re.sub(r"<[^>]*>", "", heading)
        heading = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
        ordinal = counts.get(slug, 0)
        counts[slug] = ordinal + 1
        result.add(slug + (f"-{ordinal}" if ordinal else ""))
    return result


def guarded(condition: str, required: tuple[str, ...]) -> bool:
    """Accept only the reviewed conjunction; extra disjunctions cannot weaken it."""
    condition = condition.strip().removeprefix("${{").removesuffix("}}").strip()
    if "||" in condition or "(" in condition or ")" in condition:
        return False
    terms = {re.sub(r"\s+", " ", term.strip()) for term in condition.split("&&") if term.strip()}
    return terms == set(required)


def workflow_issues(root: Path) -> list[str]:
    """Inspect executable YAML locations, immutable actions and permission ceilings."""
    issues: list[str] = []
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        try:
            value = yaml.safe_load(path.read_text())
            jobs = value["jobs"]
            if not isinstance(jobs, dict) or not isinstance(value.get("permissions"), dict):
                raise ValueError("Invalid workflow shape")
            for name, job in jobs.items():
                if not isinstance(job, dict):
                    raise ValueError("Invalid job shape")
                permissions = job.get("permissions", value["permissions"])
                if not isinstance(permissions, dict) or any(
                    level not in {"read", "write", "none"} for level in permissions.values()
                ):
                    issues.append(f"Invalid permissions: {path.name}/{name}")
                allowed_write = (
                    {"pages", "id-token"}
                    if path.name == "docs.yml" and name == "deploy"
                    else {"id-token"}
                    if path.name == "publish.yml" and name == "publish"
                    else set()
                )
                if any(
                    level == "write" and scope not in allowed_write
                    for scope, level in permissions.items()
                ):
                    issues.append(f"Excess workflow permissions: {path.name}/{name}")
                for step in job.get("steps", []):
                    if not isinstance(step, dict):
                        raise ValueError("Invalid workflow step")
                    action = step.get("uses", "")
                    if (
                        action
                        and not action.startswith("./")
                        and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)
                    ):
                        issues.append(f"Unpinned action: {path.name}/{name}")
                    if path.name == "docs.yml" and action.startswith(
                        (
                            "actions/configure-pages@",
                            "actions/upload-pages-artifact@",
                            "actions/deploy-pages@",
                        )
                    ):
                        condition = str(job.get("if", "")) + " && " + str(step.get("if", ""))
                        if not guarded(
                            condition,
                            (
                                "vars.PAGES_ENABLED == 'true'",
                                "github.event.repository.private == false",
                                "github.ref == 'refs/heads/main'",
                            ),
                        ):
                            issues.append(
                                "Reviewed private documentation publication guard is missing"
                            )
            if path.name == "publish.yml":
                guard = str(jobs.get("verify", {}).get("if", ""))
                if not guarded(
                    guard,
                    ("vars.RELEASE_ENABLED == 'true'", "github.event.repository.private == false"),
                ):
                    issues.append("Reviewed private-release publication guard is missing")
                publish = jobs.get("publish", {})
                if publish.get("needs") != "verify" or publish.get("environment") != "pypi":
                    issues.append("Release must reuse verification under the pypi environment")
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
            issues.append(f"Invalid workflow structure: {path.name}")
    return issues


def inspect(root: Path) -> dict[str, object]:
    issues: list[str] = []
    root = root.resolve()
    source = root / "src/verboisy"
    modules = sorted(source.rglob("*.py"))
    inventory = public_files(root)
    documents = sorted(path for path in inventory if path.suffix.lower() == ".md")
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
        text = unfenced(path.read_text(encoding="utf-8"))
        html = Destinations()
        html.feed(markdown.markdown(text))
        destinations = html.links
        for raw in destinations:
            raw = raw.strip().split(" ", 1)[0].strip("<>")
            target, _, fragment = raw.partition("#")
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("//"):
                continue
            resolved = path.parent / unquote(target) if target else path
            if not resolved.exists():
                issues.append(f"Broken local link in {path.relative_to(root)}: {target}")
            elif (
                fragment
                and resolved.suffix.lower() == ".md"
                and unquote(fragment) not in anchors(resolved.read_text(encoding="utf-8"))
            ):
                issues.append(f"Broken local anchor in {path.relative_to(root)}: {raw}")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    tree = ast.parse((source / "__init__.py").read_text(encoding="utf-8"))
    versions = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets)
    ]
    if versions != [project["project"]["version"]]:
        issues.append("Package version and public __version__ differ")
    if (
        project["project"].get("license") != "LicenseRef-Verboisy-Source-Inspection-2.0"
        or not (root / "LICENSE").is_file()
    ):
        issues.append("License identifier and current distribution terms disagree")
    else:
        terms = (root / "LICENSE").read_text(encoding="utf-8")
        required = (
            "VERBOISY SOURCE INSPECTION LICENSE 2.0",
            "SPDX-License-Identifier: LicenseRef-Verboisy-Source-Inspection-2.0",
            "Additional rights require a separate written agreement",
            "Third-party libraries, dependencies, vendored packages",
        )
        if not all(marker in terms for marker in required):
            issues.append("Source-inspection license is missing required scope or notices")
    matrix = json.loads((root / "evals/release-matrix.json").read_text(encoding="utf-8"))
    if [gate["id"] for gate in matrix["gates"]] != list(range(1, 8)):
        issues.append("Release matrix must retain all seven gates")
    if (root / "ARCHITECTURE.md").read_bytes() != (root / "docs/architecture.md").read_bytes():
        issues.append("Architecture entry points disagree")
    issues.extend(workflow_issues(root))
    for report_path in (root / "evals/results").glob("*.json"):
        report = json.loads(report_path.read_text())
        if report.get("qualification_applies_to_current_source") is True:
            hashes = report.get("source_fingerprints", {})
            if not isinstance(hashes, dict) or not hashes:
                issues.append("Current qualification has no source fingerprints")
                continue
            relevant = {
                p.relative_to(root).as_posix()
                for p in inventory
                if p.is_file() and not p.relative_to(root).as_posix().startswith("evals/results/")
            }
            if set(hashes) != relevant:
                issues.append("Current qualification fingerprint inventory differs")
            for name, digest in hashes.items():
                path = root / name
                if (
                    not path.resolve().is_relative_to(root)
                    or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest
                ):
                    issues.append(f"Stale current source fingerprint: {name}")
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
