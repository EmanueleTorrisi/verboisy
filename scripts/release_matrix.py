# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Record explicit release reviews against source and evidence hashes; never certify truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = Path("evals/release-matrix.json")
SOURCE_DIRS = (
    "src",
    "tests",
    "scripts",
    "docs",
    "examples",
    "native",
    "docker",
    "benchmarks",
    ".github",
    "evals",
)
IGNORED = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_matrix(root: Path = ROOT) -> dict[str, Any]:
    return json.loads((root / MATRIX).read_text(encoding="utf-8"))


def source_digest(root: Path = ROOT) -> str:
    """Hash release inputs, excluding generated results and review bookkeeping."""
    paths = {p for p in root.iterdir() if p.is_file()}
    for name in SOURCE_DIRS:
        paths.update(p for p in (root / name).rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root)
        if (
            any(part in IGNORED for part in relative.parts)
            or relative.as_posix().startswith("evals/results/")
            or path.suffix in {".pyc", ".so", ".pyd", ".db", ".xml"}
            and relative.parts[0] == "src"
            or relative.name in {".coverage", "coverage.xml", ".env", ".git"}
        ):
            continue
        if path.is_symlink():
            raise ValueError(f"Source symlink requires review: {relative}")
        data = path.read_bytes()
        if relative == MATRIX:
            value = json.loads(data)
            for key in ("status", "production_status"):
                value.pop(key, None)
            for gate in value["gates"]:
                for key in ("status", "review"):
                    gate.pop(key, None)
            data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        digest.update(relative.as_posix().encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def revision(root: Path = ROOT) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def evidence_path(name: str, root: Path = ROOT) -> Path:
    path = root / name
    if (
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or not path.resolve().is_relative_to((root / "evals/results").resolve())
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size == 0
    ):
        raise ValueError("Evidence must be a nonempty regular file under evals/results")
    return path


def gate_state(gate: dict[str, Any], digest: str, root: Path = ROOT) -> str:
    if gate.get("status") != "complete":
        return str(gate.get("status", "not_started"))
    review = gate.get("review") or {}
    if not isinstance(review, dict):
        return "stale_or_incomplete_review"
    if (
        not gate.get("criteria")
        or review.get("source_digest") != digest
        or not review.get("reviewer")
        or not review.get("reviewed_at")
        or review.get("attestation") != f"I reviewed every criterion for gate {gate['id']}"
        or not review.get("evidence")
        or set(review.get("findings", {})) != set(gate.get("criteria", {}))
        or not all(str(v).strip() for v in review.get("findings", {}).values())
    ):
        return "stale_or_incomplete_review"
    try:
        for item in review["evidence"]:
            if sha256(evidence_path(item["path"], root)) != item["sha256"]:
                return "stale_evidence"
    except (OSError, ValueError, KeyError, TypeError):
        return "stale_evidence"
    return "complete"


def require_complete(root: Path = ROOT) -> None:
    matrix = read_matrix(root)
    gates = matrix["gates"]
    if [gate["id"] for gate in gates] != list(range(1, 8)):
        raise ValueError("All seven release gates are required")
    digest = source_digest(root)
    pending = [str(g["id"]) for g in gates if gate_state(g, digest, root) != "complete"]
    if pending:
        raise ValueError("Pending or stale release gates: " + ", ".join(pending))


def save_matrix(matrix: dict[str, Any], root: Path = ROOT) -> None:
    path = root / MATRIX
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def review_gate(args: argparse.Namespace) -> None:
    matrix = read_matrix()
    gate = next(g for g in matrix["gates"] if g["id"] == args.gate)
    digest = source_digest()
    evidence = [{"path": name, "sha256": sha256(evidence_path(name))} for name in args.evidence]
    reviewer = args.reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer is required")
    findings = {}
    print("Evidence is recorded, not independently verified by this script.")
    for key, criterion in gate["criteria"].items():
        print(f"\n{key}: {criterion}")
        finding = input("Describe the result and its exact evidence location: ").strip()
        if not finding:
            raise ValueError("Every criterion requires a finding")
        findings[key] = finding
    expected = f"I reviewed every criterion for gate {args.gate}"
    if input(f"\nType '{expected}' to record completion: ") != expected:
        raise ValueError("Review not confirmed; no matrix changes written")
    if source_digest() != digest or any(
        sha256(evidence_path(e["path"])) != e["sha256"] for e in evidence
    ):
        raise ValueError("Source or evidence changed during review")
    gate["status"] = "complete"
    gate["review"] = {
        "reviewer": reviewer,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "git_revision": revision(),
        "source_digest": digest,
        "evidence": evidence,
        "findings": findings,
        "attestation": expected,
    }
    matrix["status"] = (
        "all_gates_reviewed"
        if all(gate_state(g, digest) == "complete" for g in matrix["gates"])
        else "qualification_in_progress"
    )
    matrix["production_status"] = "not_certified"
    save_matrix(matrix)
    print("Review recorded. No independent legal or product certification is implied.")


def configure_plan() -> None:
    matrix = read_matrix()
    limits = matrix["economic_targets"]
    for key in (
        "positive_web_run_cost_max",
        "cost_per_supported_output_row_max",
        "median_positive_web_run_seconds_max",
        "p95_positive_web_run_seconds_max",
        "total_paid_campaign_budget",
    ):
        value = float(input(f"{key} ({limits.get(key)}): "))
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Limits must be finite positive numbers")
        limits[key] = value
    if limits["p95_positive_web_run_seconds_max"] < limits["median_positive_web_run_seconds_max"]:
        raise ValueError("p95 limit must be at least the median limit")
    reviewer = input("Plan owner: ").strip()
    if not reviewer or input("Type APPROVE PLAN: ") != "APPROVE PLAN":
        raise ValueError("Plan not approved")
    limits.update(
        status="approved_plan",
        paid_campaign_authorized=True,
        approved_by=reviewer,
        approved_at=datetime.now(UTC).isoformat(),
    )
    save_matrix(matrix)
    print("Plan recorded. No paid requests were made. Previous source reviews are now stale.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("require-complete")
    commands.add_parser("configure-plan")
    review = commands.add_parser("review")
    review.add_argument("--gate", type=int, choices=range(1, 8), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--evidence", nargs="+", required=True)
    args = parser.parse_args()
    try:
        if args.command == "review":
            review_gate(args)
        elif args.command == "configure-plan":
            configure_plan()
        elif args.command == "require-complete":
            require_complete()
            print("All seven reviews match current source and evidence.")
        else:
            digest = source_digest()
            print(f"Source SHA-256: {digest}")
            for gate in read_matrix()["gates"]:
                print(f"{gate['id']}. {gate['name']}: {gate_state(gate, digest)}")
    except (OSError, ValueError, KeyError, TypeError, EOFError, StopIteration) as error:
        print(f"Release matrix: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
