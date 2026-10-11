# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run native pytest checks and reject silently skipped compiled tests."""

import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

from verboisy.evidence.native_configuration import inspect_native_builds


def checked_test_count(report: Path) -> int:
    """Require successful testcase records, including zero skipped/xfail cases."""
    root = ElementTree.parse(report).getroot()
    if root.tag == "testsuites":
        cases = root.findall("./testsuite/testcase")
    elif root.tag == "testsuite":
        cases = root.findall("./testcase")
    else:
        raise ValueError("Native pytest report has an unexpected root")
    if not cases:
        raise ValueError("Native pytest report contains no tests")
    for case in cases:
        for status in ("skipped", "failure", "error"):
            if case.find(status) is not None:
                raise ValueError(f"Native test {case.get('name', '<unnamed>')} contains {status}")
    return len(cases)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = root / "build/native/native-test-results.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    # A successful older report cannot stand in for a run that failed to produce
    # fresh XML. Fingerprints are checked before any compiled test is loaded.
    report.unlink(missing_ok=True)
    try:
        for name, build in inspect_native_builds().items():
            for field in (
                "binary_present",
                "metadata_present",
                "binary_matches_metadata",
                "sources_match_metadata",
            ):
                if build[field] is not True:
                    raise ValueError(f"{name} build failed {field}; rebuild both native modules")
    except (OSError, ValueError) as exc:
        print(f"Native build validation failed: {exc}", file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "native",
            "--no-cov",
            "-q",
            "-ra",
            "--junitxml",
            str(report),
        ],
        cwd=root,
        env=environment,
        check=False,
    )
    if result.returncode:
        return result.returncode
    try:
        count = checked_test_count(report)
    except (OSError, ElementTree.ParseError, ValueError) as exc:
        print(f"Native validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Native validation passed: {count} tests, no skips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
