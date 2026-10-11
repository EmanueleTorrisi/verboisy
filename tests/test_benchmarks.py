# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Keep benchmark measurements useful by rejecting changed or corrupt outputs."""

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.runner import main, measure
from benchmarks.workloads import CASE_NAMES, BenchmarkError, Workload, digest, make_workloads


def collect(directory):
    directory.mkdir()
    cases, store = make_workloads(16, 8, directory, list(CASE_NAMES))
    try:
        return {case.name: digest(case.validate(case.operation())) for case in cases}
    finally:
        store.close()


def test_all_workloads_have_stable_checked_outputs_across_ledgers(tmp_path):
    first = collect(tmp_path / "first")
    assert set(first) == set(CASE_NAMES)
    assert first == collect(tmp_path / "second")


def test_non_lineage_work_does_not_open_a_ledger(tmp_path):
    cases, store = make_workloads(12, 8, tmp_path, ["parse_csv", "group", "sort"])
    assert store is None
    assert not list(tmp_path.iterdir())
    for case in cases:
        case.validate(case.operation())
    parsed = cases[0].operation()
    changed = parsed.rows[0].values
    changed["note"] = "corrupted"
    parsed = replace(
        parsed, rows=(replace(parsed.rows[0], values_json=json.dumps(changed)), *parsed.rows[1:])
    )
    with pytest.raises(BenchmarkError, match="values, types or order"):
        cases[0].validate(parsed)


def test_measure_rejects_output_changed_after_warmup():
    values = iter([{"value": 1}, {"value": 2}])
    case = Workload("changing", 1, "in_memory", lambda: next(values), lambda value: value)
    with pytest.raises(BenchmarkError, match="changed between repetitions"):
        measure(case, 1, None)


def test_profile_and_memory_samples_preserve_correctness(tmp_path):
    case = Workload("literal", 1, "in_memory", lambda: ["李雷"], lambda value: value)
    result = measure(case, 2, tmp_path)
    assert len(result["samples"]) == 2
    assert all(sample["cpu_ns"] >= 0 and sample["wall_ns"] >= 0 for sample in result["samples"])
    assert result["peak_python_bytes"] > 0
    assert result["output_sha256"] == digest(["李雷"])
    assert Path(result["profile"]).is_file()
    assert result["correctness_checked"] is True


@pytest.mark.parametrize(
    "option,value", [("--rows", "0"), ("--lineage-rows", "2001"), ("--repeats", "101")]
)
def test_invalid_sizes_fail_before_output(tmp_path, option, value):
    output = tmp_path / "result.json"
    with pytest.raises(SystemExit) as error:
        main([option, value, "--output", str(output)])
    assert error.value.code == 2
    assert not output.exists()


def test_report_records_real_source_hashes_without_configured_secrets(tmp_path, monkeypatch):
    database = tmp_path / "research.db"
    database.write_bytes(b"untouched research ledger")
    monkeypatch.setenv("SQLITE_DB_PATH", str(database))
    monkeypatch.setenv("OPENAI_API_KEY", "benchmark-secret-sentinel")
    output = tmp_path / "results" / "report.json"
    main(["--rows", "8", "--case", "parse_json", "--repeats", "1", "--output", str(output)])
    body = output.read_text()
    report = json.loads(body)
    root = Path(__file__).resolve().parents[1]
    assert (
        report["source_hashes"]["poetry.lock"]
        == hashlib.sha256((root / "poetry.lock").read_bytes()).hexdigest()
    )
    assert report["method"]["network_and_model_work"] is False
    assert [result["case"] for result in report["results"]] == ["parse_json"]
    assert "benchmark-secret-sentinel" not in body
    assert str(database) not in body
    assert database.read_bytes() == b"untouched research ledger"


def test_correctness_checks_survive_optimized_python():
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "from benchmarks.workloads import require; require(False, 'invalid')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "BenchmarkError: invalid" in result.stderr
