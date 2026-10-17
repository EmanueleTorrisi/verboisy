# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Select exact tested artifacts, detect stale inputs and explicitly confirm public uploads."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from check_distribution import inspect_archive
from release_matrix import ROOT, require_complete, sha256, source_digest
from verify_release import BASE_CHECKS, PACKAGE_CHECKS

CANDIDATE = Path("build/release-candidate.json")
TARGETS = {"testpypi": "https://test.pypi.org/legacy/", "pypi": "https://upload.pypi.org/legacy/"}


def verified_artifacts(value: dict[str, Any], root: Path = ROOT) -> list[Path]:
    if value.get("source_digest") != source_digest(root):
        raise ValueError("Source changed: rerun verification and select new artifacts")
    artifacts = value.get("artifacts", [])
    if len(artifacts) != 2:
        raise ValueError("Exactly one tested wheel and one sdist are required")
    paths = []
    for artifact in artifacts:
        relative = Path(artifact["path"])
        path = root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or path.is_symlink()
            or not path.resolve().is_relative_to((root / "build/release-checks").resolve())
            or not path.is_file()
            or sha256(path) != artifact["sha256"]
        ):
            raise ValueError("Artifact missing, moved outside staging, or modified")
        paths.append(path)
    if (
        sum(p.suffix == ".whl" for p in paths) != 1
        or sum(p.name.endswith(".tar.gz") for p in paths) != 1
    ):
        raise ValueError("Expected one wheel and one sdist")
    if inspect_archive(paths[0]) != inspect_archive(paths[1]):
        raise ValueError("Wheel and sdist contracts differ")
    return paths


def select_report(path: Path, root: Path = ROOT) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    outcomes = report.get("checks", [])
    successful = {item["name"] for item in outcomes if item.get("exit_code") == 0}
    if (
        report.get("report_type") != "engineering"
        or report.get("passed") is not True
        or report.get("source_unchanged") is not True
        or not (BASE_CHECKS | PACKAGE_CHECKS).issubset(successful)
        or any(item.get("exit_code") != 0 for item in outcomes)
    ):
        raise ValueError("Use a passing current engineering report with --package checks")
    verified_artifacts(report, root)
    return {
        "source_digest": report["source_digest"],
        "artifacts": report["artifacts"],
        "report": str(path.resolve()),
        "report_sha256": sha256(path),
    }


def read_candidate(root: Path = ROOT) -> tuple[dict[str, Any], list[Path]]:
    candidate = json.loads((root / CANDIDATE).read_text(encoding="utf-8"))
    report_path = Path(candidate["report"])
    if not report_path.is_file() or sha256(report_path) != candidate["report_sha256"]:
        raise ValueError("The selected engineering report changed or disappeared")
    current = select_report(report_path, root)
    if current != candidate:
        raise ValueError("Candidate and engineering report disagree")
    return candidate, verified_artifacts(candidate, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--report", type=Path, required=True)
    commands.add_parser("show")
    upload = commands.add_parser("upload")
    upload.add_argument("--target", choices=TARGETS, required=True)
    upload.add_argument("--production", action="store_true")
    upload.add_argument("--twine", default=str(ROOT / "build/release-tools/bin/twine"))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            candidate = select_report(args.report)
            destination = ROOT / CANDIDATE
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
            print("Selected the exact tested artifacts; no rebuild and no upload performed.")
        candidate, paths = read_candidate()
        print(json.dumps(candidate, indent=2))
        if args.command == "upload":
            if args.production:
                require_complete()
            else:
                print(
                    "Source-inspection/evaluation publication; "
                    "full release qualification is pending."
                )
            expected = f"PUBLIC {args.target}"
            if input(f"Anyone can download these files. Type '{expected}': ") != expected:
                raise ValueError("Upload not confirmed")
            read_candidate()
            environment = {k: v for k, v in os.environ.items() if not k.startswith("TWINE_")}
            subprocess.run(
                [
                    args.twine,
                    "upload",
                    "--repository-url",
                    TARGETS[args.target],
                    "--username",
                    "__token__",
                    *map(str, paths),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        EOFError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Release packaging: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
