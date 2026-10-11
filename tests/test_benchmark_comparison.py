# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A speed ratio is useful only when workload and output contracts still match."""

import copy
import json

import pytest

from benchmarks.comparison import compare_reports, main
from benchmarks.runner import main as benchmark


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "before.json"
    benchmark(["--case", "parse_json", "--rows", "4", "--repeats", "1", "--output", str(path)])
    value = json.loads(path.read_text(encoding="utf-8"))
    # Comparison tests exercise report contracts, not the host timer resolution.
    # Tiny workloads can legitimately consume zero CPU ticks on Windows.
    for result in value["results"]:
        for sample in result["samples"]:
            sample.update(cpu_ns=1000, wall_ns=1000)
        result.update(median_cpu_ns=1000, median_wall_ns=1000)
    return value


def test_compatible_changes_show_ratios_and_source_identity(report):
    after = copy.deepcopy(report)
    first, second = report["results"][0], after["results"][0]
    for metric in ("cpu_ns", "wall_ns"):
        first["samples"][0][metric] = first["median_" + metric] = 1000
        second["samples"][0][metric] = 500
        second["median_" + metric] = second["samples"][0][metric]
    after["source_hashes"]["new.cpp"] = "a" * 64
    after["quote_matcher_backend"] = "native"
    after["native_module_sha256"] = "b" * 64
    result = compare_reports(report, after)
    assert result["all_cases_comparable"] is True
    assert result["results"][0]["cpu_speedup"] == 2
    assert result["results"][0]["cpu_reduction_fraction"] == 0.5
    assert result["changed_sources"] == [
        {"path": "new.cpp", "before_sha256": None, "after_sha256": "a" * 64}
    ]
    assert result["backends"] == {"before": report["quote_matcher_backend"], "after": "native"}
    assert compare_reports(after, report)["results"][0]["cpu_speedup"] == 0.5


@pytest.mark.parametrize(
    "key", ["python", "platform", "machine", "sqlite_version", "dependencies", "method"]
)
def test_environment_differences_suppress_ratios(report, key):
    after = copy.deepcopy(report)
    if isinstance(after[key], dict):
        after[key]["changed"] = "different"
    else:
        after[key] = "different"
    result = compare_reports(report, after)
    assert result["environment_differences"] == [key]
    assert result["all_cases_comparable"] is False
    assert "cpu_speedup" not in result["results"][0]


@pytest.mark.parametrize(
    "key,value",
    [("rows", 5), ("gc_enabled", False), ("output_sha256", "a" * 64), ("domain", "different")],
)
def test_changed_workloads_or_outputs_suppress_ratios(report, key, value):
    after = copy.deepcopy(report)
    after["results"][0][key] = value
    result = compare_reports(report, after)["results"][0]
    assert key in result["reasons"]
    assert "cpu_speedup" not in result


def test_case_specific_fixtures_and_missing_cases(report):
    after = copy.deepcopy(report)
    after["lineage_fixture_sha256"] = "a" * 64
    assert compare_reports(report, after)["all_cases_comparable"] is True
    after["fixture_sha256"] = "b" * 64
    assert "fixture_sha256" in compare_reports(report, after)["results"][0]["reasons"]
    for name, key in [
        ("lineage_scalar", "lineage_fixture_sha256"),
        ("quote_python", "quote_fixture_sha256"),
    ]:
        before = copy.deepcopy(report)
        after = copy.deepcopy(report)
        before["results"][0]["case"] = after["results"][0]["case"] = name
        before[key], after[key] = "a" * 64, "b" * 64
        assert key in compare_reports(before, after)["results"][0]["reasons"]
    after = copy.deepcopy(report)
    after["results"][0]["case"] = "other"
    result = compare_reports(report, after)
    assert [r["reasons"] for r in result["results"]] == [["missing_after"], ["missing_before"]]


@pytest.mark.parametrize(
    "mutation",
    [
        "median",
        "boolean",
        "nan",
        "negative",
        "huge",
        "duplicate",
        "unchecked",
        "version",
        "hash",
        "samples",
    ],
)
def test_invalid_reports_rejected_before_comparison(report, mutation):
    after = copy.deepcopy(report)
    result = after["results"][0]
    if mutation == "median":
        result["median_cpu_ns"] += 1
    elif mutation in ("boolean", "nan", "negative", "huge"):
        result["samples"][0]["cpu_ns"] = {
            "boolean": True,
            "nan": float("nan"),
            "negative": -1,
            "huge": 10**500,
        }[mutation]
    elif mutation == "duplicate":
        after["results"].append(copy.deepcopy(result))
    elif mutation == "unchecked":
        result["correctness_checked"] = False
    elif mutation == "version":
        after["benchmark_version"] = "99"
    elif mutation == "hash":
        result["output_sha256"] = "invalid"
    else:
        result["samples"] = []
    with pytest.raises(ValueError):
        compare_reports(report, after)


def test_zero_measurements_are_not_reported_as_speedups(report):
    after = copy.deepcopy(report)
    after["results"][0]["samples"][0]["cpu_ns"] = 0
    after["results"][0]["median_cpu_ns"] = 0
    assert compare_reports(report, after)["results"][0]["reasons"] == ["timing_not_resolved"]
    report["results"][0]["peak_python_bytes"] = 0
    assert compare_reports(report, report)["results"][0]["python_allocation_ratio"] is None


def test_cli_writes_comparison_and_preserves_inputs(report, tmp_path, capsys):
    before, after, output = (
        tmp_path / name for name in ("before.json", "after.json", "comparison.json")
    )
    before.write_text(json.dumps(report), encoding="utf-8")
    after.write_text(json.dumps(report), encoding="utf-8")
    original = before.read_bytes()
    assert main([str(before), str(after), "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["all_cases_comparable"] is True
    assert before.read_bytes() == original
    changed = copy.deepcopy(report)
    changed["platform"] = "different"
    after.write_text(json.dumps(changed), encoding="utf-8")
    assert main([str(before), str(after)]) == 1
    assert '"status": "incompatible"' in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main([str(before), str(after), "--output", str(before)])
    assert error.value.code == 2
    assert before.read_bytes() == original


@pytest.mark.parametrize("body", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "invalid JSON"])
def test_cli_rejects_invalid_json_before_writing(tmp_path, body):
    source, output = tmp_path / "source.json", tmp_path / "output.json"
    source.write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(source), str(source), "--output", str(output)])
    assert error.value.code == 2
    assert not output.exists()
