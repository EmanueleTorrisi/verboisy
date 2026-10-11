# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compare saved benchmark reports without executing workloads or opening ledgers."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

from verboisy.storage.exporters import _atomic_write

ENVIRONMENT = ("python", "platform", "machine", "sqlite_version", "dependencies", "method")
DIGEST = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def _integer(value: Any) -> bool:
    # JSON booleans must not masquerade as integer counters or repetition counts.
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    # Measurements originate from nanosecond counters. Bound their range before
    # float conversion so malformed reports cannot overflow ratio arithmetic.
    return type(value) in (int, float) and 0 <= value <= 2**63 - 1 and math.isfinite(value)


def _validate(report: Any) -> dict[str, dict[str, Any]]:
    _require(isinstance(report, dict), "Report must be an object")
    for key in ("benchmark_version", "fixture_version"):
        _require(report.get(key) == "1", f"Unsupported or missing {key}")
    for key in ("python", "platform", "machine", "sqlite_version", "quote_matcher_backend"):
        _require(isinstance(report.get(key), str) and bool(report[key]), f"Invalid {key}")
    for key in ("dependencies", "source_hashes", "method"):
        _require(isinstance(report.get(key), dict) and bool(report[key]), f"Invalid {key}")
    _require(
        all(isinstance(k, str) and isinstance(v, str) for k, v in report["dependencies"].items()),
        "Invalid dependency versions",
    )
    _require(
        all(isinstance(k, str) and _digest(v) for k, v in report["source_hashes"].items()),
        "Invalid source hashes",
    )
    for key in ("fixture_sha256", "lineage_fixture_sha256"):
        _require(_digest(report.get(key)), f"Invalid {key}")
    for key in ("quote_fixture_sha256", "native_module_sha256"):
        _require(report.get(key) is None or _digest(report[key]), f"Invalid {key}")
    repeats = report.get("repeats")
    _require(_integer(repeats) and 1 <= repeats <= 100, "Invalid repeats")
    _require(isinstance(report.get("results"), list) and bool(report["results"]), "Missing results")
    results = {}
    for result in report["results"]:
        _require(isinstance(result, dict), "Result must be an object")
        name = result.get("case")
        _require(
            isinstance(name, str) and bool(name) and name not in results, "Invalid/duplicate case"
        )
        _require(_integer(result.get("rows")) and result["rows"] > 0, f"Invalid rows: {name}")
        _require(isinstance(result.get("gc_enabled"), bool), f"Invalid GC state: {name}")
        _require(isinstance(result.get("domain"), str) and bool(result["domain"]), "Invalid domain")
        _require(result.get("correctness_checked") is True, f"Unchecked output: {name}")
        _require(_digest(result.get("output_sha256")), f"Invalid output digest: {name}")
        _require(
            _integer(result.get("peak_python_bytes")) and _number(result["peak_python_bytes"]),
            f"Invalid allocation measurement: {name}",
        )
        samples = result.get("samples")
        _require(isinstance(samples, list) and len(samples) == repeats, f"Invalid samples: {name}")
        for metric in ("cpu_ns", "wall_ns"):
            _require(
                all(
                    isinstance(s, dict) and _integer(s.get(metric)) and _number(s[metric])
                    for s in samples
                ),
                f"Invalid {metric} samples: {name}",
            )
            median = result.get("median_" + metric)
            _require(
                _number(median) and median == statistics.median(s[metric] for s in samples),
                f"Median does not match samples: {name}/{metric}",
            )
        results[name] = result
    return results


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Report ratios only for matched, checked workloads with compatible metadata.

    Source and native binary changes are expected during optimization and recorded
    separately. Equal digests show equal benchmark output, not external factual truth.
    """
    left, right = _validate(before), _validate(after)
    environment = [key for key in ENVIRONMENT if before[key] != after[key]]
    results = []
    for name in dict.fromkeys([*left, *right]):
        first, second = left.get(name), right.get(name)
        item: dict[str, Any] = {"case": name, "status": "incompatible", "reasons": []}
        reasons = item["reasons"]
        if first is None or second is None:
            reasons.append("missing_before" if first is None else "missing_after")
        else:
            reasons.extend("environment:" + key for key in environment)
            for key in ("rows", "domain", "gc_enabled", "output_sha256"):
                if first[key] != second[key]:
                    reasons.append(key)
            fixture = (
                "lineage_fixture_sha256"
                if name.startswith("lineage_")
                else "quote_fixture_sha256"
                if name.startswith("quote_")
                else "fixture_sha256"
            )
            if before.get(fixture) != after.get(fixture) or before.get(fixture) is None:
                reasons.append(fixture)
            if any(
                first[key] <= 0 or second[key] <= 0 for key in ("median_cpu_ns", "median_wall_ns")
            ):
                reasons.append("timing_not_resolved")
            item["before"] = {
                key: first[key]
                for key in ("rows", "median_cpu_ns", "median_wall_ns", "peak_python_bytes")
            }
            item["after"] = {
                key: second[key]
                for key in ("rows", "median_cpu_ns", "median_wall_ns", "peak_python_bytes")
            }
            if not reasons:
                item.update(
                    status="comparable",
                    cpu_speedup=first["median_cpu_ns"] / second["median_cpu_ns"],
                    cpu_reduction_fraction=1 - second["median_cpu_ns"] / first["median_cpu_ns"],
                    wall_speedup=first["median_wall_ns"] / second["median_wall_ns"],
                    python_allocation_ratio=second["peak_python_bytes"] / first["peak_python_bytes"]
                    if first["peak_python_bytes"]
                    else None,
                )
        results.append(item)
    sources = dict.fromkeys([*before["source_hashes"], *after["source_hashes"]])
    return {
        "comparison_version": "1",
        "all_cases_comparable": all(item["status"] == "comparable" for item in results),
        "environment_differences": environment,
        "changed_sources": [
            {
                "path": path,
                "before_sha256": before["source_hashes"].get(path),
                "after_sha256": after["source_hashes"].get(path),
            }
            for path in sources
            if before["source_hashes"].get(path) != after["source_hashes"].get(path)
        ],
        "backends": {
            "before": before["quote_matcher_backend"],
            "after": after["quote_matcher_backend"],
        },
        "native_modules": {
            "before": before.get("native_module_sha256"),
            "after": after.get("native_module_sha256"),
        },
        "repetitions": {"before": before["repeats"], "after": after["repeats"]},
        "results": results,
        "limits": (
            "Synthetic workload comparison; no significance test or speed threshold. "
            "Allocations are traced Python bytes, not RSS."
        ),
    }


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        _require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() in (args.before.resolve(), args.after.resolve()):
            raise ValueError("Output must not overwrite an input report")
        reports = [
            json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
            )
            for path in (args.before, args.after)
        ]
        comparison = compare_reports(*reports)
        if args.output:
            _atomic_write(
                args.output, lambda stream: json.dump(comparison, stream, indent=2, allow_nan=False)
            )
            print(str(args.output.resolve()))
        else:
            print(json.dumps(comparison, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    # A slower compatible run succeeds: this command checks comparisons, not speed.
    return 0 if comparison["all_cases_comparable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
