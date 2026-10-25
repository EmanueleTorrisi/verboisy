# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Benchmark evidence cannot pass by dropping assertions or corrupting typed values."""

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/benchmark_efficiency.py"
BENCH = runpy.run_path(str(SCRIPT))
SOURCE = b"original input"
SOURCE_HASH = hashlib.sha256(SOURCE).hexdigest()


def write_bundle(root, values, proofs):
    output = root / "rows.jsonl"
    output.write_text("".join(json.dumps(v) + "\n" for v in values), encoding="utf-8")
    evidence = output.with_name(output.name + ".evidence.jsonl")
    evidence.write_text("".join(json.dumps(v) + "\n" for v in proofs), encoding="utf-8")
    source = output.with_name(output.name + ".source.bin")
    source.write_bytes(SOURCE)
    output.with_name(output.name + ".manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": SOURCE_HASH,
                "files": {p.name: BENCH["digest"](p) for p in [output, evidence, source]},
            }
        )
    )
    return output


@pytest.mark.parametrize(
    "mutation",
    [None, "typed_value", "proof_value", "ordinal", "location", "transformed", "missing", "extra"],
)
def test_independent_checker_rejects_wrong_typed_data_and_incomplete_evidence(tmp_path, mutation):
    value = BENCH["record"](0)
    proof = {
        "source_values": dict(value),
        "source_row": 1,
        "output_row": 1,
        "line_start": 1,
        "line_end": 1,
        "output_is_source": True,
    }
    if mutation == "typed_value":
        value["available"] = 1  # Python equality alone would incorrectly consider True == 1.
    elif mutation == "proof_value":
        proof["source_values"]["missing"] = "null"
    elif mutation == "ordinal":
        proof["source_row"] = 2
    elif mutation == "location":
        proof["line_end"] = 2
    elif mutation == "transformed":
        proof["output_is_source"] = False
    values, proofs = [value], [proof]
    if mutation == "missing":
        proofs = []
    if mutation == "extra":
        values = values * 2
        proofs = proofs * 2
    output = write_bundle(tmp_path, values, proofs)
    if mutation is None:
        assert BENCH["verify_bundle"](output, 1, SOURCE_HASH) == 1
    else:
        with pytest.raises((BENCH["BenchmarkError"], ValueError)):
            BENCH["verify_bundle"](output, 1, SOURCE_HASH)


def test_benchmark_checks_remain_active_under_optimized_python():
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "import runpy,sys; runpy.run_path(sys.argv[1])['require'](False,'invalid')",
            str(SCRIPT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "BenchmarkError: invalid" in result.stderr


@pytest.mark.parametrize("mutation", ["hash", "source", "path", "count", "missing", "source_bytes"])
def test_bundle_hash_source_paths_and_declared_count_are_checked(tmp_path, mutation):
    value = BENCH["record"](0)
    proof = {
        "source_values": value,
        "source_row": 1,
        "output_row": 1,
        "line_start": 1,
        "line_end": 1,
        "output_is_source": True,
    }
    output = write_bundle(tmp_path, [value], [proof])
    path = output.with_name(output.name + ".manifest.json")
    manifest = json.loads(path.read_text())
    if mutation == "hash":
        manifest["files"][output.name] = "wrong"
    elif mutation == "source":
        manifest["source_sha256"] = "different"
    elif mutation == "path":
        manifest["files"] = {"../outside": "wrong"}
    elif mutation == "missing":
        manifest["files"].pop(output.name)
    elif mutation == "source_bytes":
        source = output.with_name(output.name + ".source.bin")
        source.write_bytes(b"changed")
        manifest["files"][source.name] = BENCH["digest"](source)
    path.write_text(json.dumps(manifest))
    with pytest.raises(BENCH["BenchmarkError"]):
        BENCH["verify_bundle"](output, 2 if mutation == "count" else 1, SOURCE_HASH)
