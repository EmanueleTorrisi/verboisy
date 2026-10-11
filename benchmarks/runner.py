# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Measure warmed local work with correctness checks outside timing intervals."""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from verboisy.evidence.quote_match import native_module_path
from verboisy.storage.exporters import _atomic_write

from benchmarks.workloads import (
    CASE_NAMES,
    OPTIONAL_CASE_NAMES,
    Workload,
    digest,
    make_workloads,
    quote_cases,
    records,
    require,
)


def measure(case: Workload, repeats: int, profile_dir: Path | None) -> dict[str, Any]:
    # Warm caches first. Checks and hashing are intentionally outside every timer.
    expected = digest(case.validate(case.operation()))
    samples = []
    for _ in range(repeats):
        gc.collect()
        cpu = time.process_time_ns()
        wall = time.perf_counter_ns()
        output = case.operation()
        wall_elapsed = time.perf_counter_ns() - wall
        cpu_elapsed = time.process_time_ns() - cpu
        require(digest(case.validate(output)) == expected, "Output changed between repetitions")
        samples.append({"cpu_ns": cpu_elapsed, "wall_ns": wall_elapsed})
        del output
    gc.collect()
    tracemalloc.start()
    try:
        output = case.operation()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    require(digest(case.validate(output)) == expected, "Memory sample output differs")
    del output
    profile_path = None
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        path = profile_dir / (case.name + ".prof")
        profile = cProfile.Profile()
        output = profile.runcall(case.operation)
        require(digest(case.validate(output)) == expected, "Profile sample output differs")
        profile.dump_stats(path)
        profile_path = str(path.resolve())
    return {
        "case": case.name,
        "rows": case.rows,
        "domain": case.domain,
        "gc_enabled": gc.isenabled(),
        "samples": samples,
        "median_cpu_ns": statistics.median(s["cpu_ns"] for s in samples),
        "median_wall_ns": statistics.median(s["wall_ns"] for s in samples),
        "peak_python_bytes": peak,
        "output_sha256": expected,
        "correctness_checked": True,
        "profile": profile_path,
    }


def bounded(limit: int):
    def parse(value: str) -> int:
        number = int(value)
        if not 1 <= number <= limit:
            raise argparse.ArgumentTypeError(f"Must be between 1 and {limit}")
        return number

    return parse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=bounded(100000), default=1000)
    parser.add_argument("--lineage-rows", type=bounded(2000), default=100)
    parser.add_argument("--repeats", type=bounded(100), default=3)
    parser.add_argument("--case", action="append", choices=(*CASE_NAMES, *OPTIONAL_CASE_NAMES))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument(
        "--scalar-native-quotes",
        action="store_true",
        help="Disable native batching in the verifier workload",
    )
    args = parser.parse_args(argv)
    selected = list(dict.fromkeys(args.case or CASE_NAMES))
    with tempfile.TemporaryDirectory(prefix="verboisy-benchmark-") as directory:
        cases, store = make_workloads(
            args.rows,
            args.lineage_rows,
            Path(directory),
            selected,
            batch_quotes=not args.scalar_native_quotes,
        )
        try:
            results = [measure(case, args.repeats, args.profile_dir) for case in cases]
        finally:
            if store is not None:
                store.close()
    root = Path(__file__).resolve().parents[1]
    report = {
        "benchmark_version": "1",
        "fixture_version": "1",
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sqlite_version": sqlite3.sqlite_version,
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("pydantic", "jsonschema")
        },
        "source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "pyproject.toml",
                "poetry.lock",
                "benchmarks/runner.py",
                "benchmarks/workloads.py",
                *[str(path.relative_to(root)) for path in sorted((root / "native").glob("*.cpp"))],
                *[str(path.relative_to(root)) for path in sorted((root / "native").glob("*.hpp"))],
                "scripts/build_native.py",
                *[str(path.relative_to(root)) for path in sorted((root / "src").rglob("*.py"))],
            )
        },
        "fixture_sha256": digest(records(args.rows)),
        "lineage_fixture_sha256": digest(records(args.lineage_rows)),
        "quote_fixture_sha256": digest(quote_cases(args.rows))
        if any(name in selected for name in OPTIONAL_CASE_NAMES)
        else None,
        "quote_matcher_backend": os.environ.get("VERBOISY_QUOTE_MATCHER", "python"),
        "native_verifier_quote_mode": "scalar"
        if args.scalar_native_quotes
        or os.environ.get("VERBOISY_QUOTE_MATCHER", "python") != "native"
        else "batch",
        "native_module_sha256": hashlib.sha256(native_module_path().read_bytes()).hexdigest()
        if any(name in selected for name in ("quote_native", "quote_batch_native"))
        or os.environ.get("VERBOISY_QUOTE_MATCHER") == "native"
        else None,
        "repeats": args.repeats,
        "results": results,
        "method": {
            "network_and_model_work": False,
            "fixture_setup_timed": False,
            "correctness_checks_timed": False,
            "warmup_runs": 1,
            "memory": "Separate invocation; traced Python allocations only, not process RSS",
            "timing": "Unprofiled process CPU and monotonic wall time; GC state recorded per case",
            "comparisons": (
                "Compare matching cases, sizes, fixture digests and environments; "
                "no CI speed threshold"
            ),
        },
    }
    if args.output:
        _atomic_write(
            args.output,
            lambda stream: json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2),
        )
        print(str(args.output.resolve()))
    else:
        print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
