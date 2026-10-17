# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Execute engineering checks and retain source-bound results without completing release gates."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime

from release_matrix import ROOT, revision, sha256, source_digest

BASE_CHECKS = {"lock", "repository", "lint", "format", "types", "offline", "quickstart", "docs"}
PACKAGE_CHECKS = {"build", "distribution", "twine"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poetry", default=str(ROOT / "build/release-tools/bin/poetry"))
    parser.add_argument("--twine", default=str(ROOT / "build/release-tools/bin/twine"))
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    started = datetime.now(UTC)
    slug = started.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    work = ROOT / "build/release-checks" / slug
    work.mkdir(parents=True)
    digest = source_digest()
    poetry = [args.poetry]
    run = [*poetry, "run"]
    checks = [
        ("lock", [*poetry, "check", "--lock"]),
        ("repository", [*run, "python", "scripts/check_repository.py", "--json"]),
        ("lint", [*run, "ruff", "check", "."]),
        ("format", [*run, "ruff", "format", "--check", "."]),
        ("types", [*run, "mypy", "src"]),
        (
            "offline",
            [
                *run,
                "pytest",
                "-m",
                "not browser and not live",
                "--cov=src",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=100",
            ],
        ),
        ("quickstart", [*run, "python", "examples/local_quickstart.py"]),
        ("docs", [*run, "mkdocs", "build", "--strict"]),
    ]
    if args.native:
        checks.extend(
            (name, [*run, "python", f"scripts/{script}.py"])
            for name, script in (
                ("native-build", "build_native"),
                ("native-tests-build", "build_native_tests"),
                ("native", "check_native_tests"),
            )
        )
    if args.browser:
        checks.append(("browser", [*run, "pytest", "-m", "browser", "-v"]))
    if args.audit:
        checks.append(("audit", [*run, "pip-audit", "--local"]))
    dist = work / "dist"
    if args.package:
        checks.extend(
            [
                ("build", [*poetry, "build", "--output", str(dist)]),
                (
                    "distribution",
                    [
                        *run,
                        "python",
                        "scripts/check_distribution.py",
                        "--dist-dir",
                        str(dist),
                        "--from-sdist",
                        "--install-smoke",
                    ],
                ),
                ("twine", []),
            ]
        )
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    environment["POETRY_VIRTUALENVS_IN_PROJECT"] = "true"
    if args.browser:
        environment["VERBOISY_REQUIRE_BROWSER"] = "1"
    outcomes = []
    for name, command in checks:
        if name == "twine":
            command = [args.twine, "check", "--strict", *map(str, sorted(dist.glob("*")))]
        log = work / f"{name}.log"
        print(f"Checking {name} … log: {log.relative_to(ROOT)}", flush=True)
        begin = time.monotonic()
        code = 1
        interrupted = False
        with log.open("w", encoding="utf-8") as output:
            try:
                code = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=False,
                ).returncode
            except KeyboardInterrupt:
                output.write("\nInterrupted by operator.\n")
                code, interrupted = 130, True
            except OSError as error:
                output.write(f"Unable to start check: {error}\n")
        outcomes.append(
            {
                "name": name,
                "command": command,
                "exit_code": code,
                "seconds": round(time.monotonic() - begin, 3),
                "log": log.relative_to(ROOT).as_posix(),
                "log_sha256": sha256(log),
            }
        )
        print(f"{name}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if interrupted:
            break
    unchanged = source_digest() == digest
    artifacts = [
        {"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)}
        for p in sorted(dist.glob("*"))
        if p.is_file()
    ]
    passed = (
        unchanged and len(outcomes) == len(checks) and all(c["exit_code"] == 0 for c in outcomes)
    )
    report = {
        "report_type": "engineering",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "source_digest": digest,
        "source_unchanged": unchanged,
        "git_revision": revision(),
        "platform": platform.platform(),
        "python": sys.version,
        "passed": passed,
        "checks": outcomes,
        "artifacts": artifacts,
        "qualification_applies_to_current_source": False,
        "scope": "Executed engineering checks only; no full release qualification",
        "limitations": [
            "Other platforms were not exercised by this invocation",
            "No real-provider or annotated 69-run acceptance campaign",
            "No legal review, independent beta or production certification",
            "Browser, native and dependency audit apply only if named in checks",
            "No current million-row or power-loss qualification",
        ],
    }
    destination = ROOT / "evals/results" / f"engineering-{slug}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {destination.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
