# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check complete verification through the actual scalar and batch C++ bindings."""

import json

import pytest
from verboisy.evidence.quote_match import native_module_path
from verboisy.evidence.verify import verify

from benchmarks.runner import main
from benchmarks.workloads import SCHEMA
from tests.test_research.test_verifier_quote_batch import mixed_errors

pytestmark = pytest.mark.native


@pytest.fixture(autouse=True)
def compiled_extension():
    if not native_module_path().is_file():
        pytest.skip("Build native verification with scripts/build_native.py")


def test_real_native_batch_has_identical_ordered_errors(monkeypatch):
    page, candidate, task = mixed_errors()
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "python")
    expected = verify(candidate, page, SCHEMA, task)
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    assert verify(candidate, page, SCHEMA, task, batch_quotes=False) == expected
    assert verify(candidate, page, SCHEMA, task) == expected


def test_whole_verifier_benchmarks_identify_dispatch_and_match_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    reports = []
    for mode in ("scalar", "batch"):
        path = tmp_path / (mode + ".json")
        flags = ["--scalar-native-quotes"] if mode == "scalar" else []
        main(["--case", "verify", "--rows", "8", "--repeats", "1", "--output", str(path), *flags])
        report = json.loads(path.read_text())
        assert report["native_verifier_quote_mode"] == mode
        reports.append(report)
    assert reports[0]["results"][0]["output_sha256"] == reports[1]["results"][0]["output_sha256"]
    assert reports[0]["native_module_sha256"] == reports[1]["native_module_sha256"]
