# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise the real native batch API, including partial-input rejection."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from verboisy.evidence.quote_batch import quotes_observed
from verboisy.evidence.quote_match import native_module_path

from benchmarks.runner import main
from tests.test_quote_batch import test_batches_match_scalar_unicode_reference as check_unicode

pytestmark = pytest.mark.native


@pytest.fixture(autouse=True)
def compiled_batch():
    if not native_module_path().is_file():
        pytest.skip("Build native batches with scripts/build_native.py")


def test_native_batch_unicode_matches_reference():
    check_unicode("native")


@pytest.mark.parametrize(
    "cases,error",
    [
        (None, TypeError),
        ("cat", TypeError),
        ([None], TypeError),
        ([("cat",)], TypeError),
        ([("cat", "cat", False), (None, "cat", False)], TypeError),
        ([("cat", None, False)], TypeError),
        ([("cat", "cat", 1)], TypeError),
        ([("cat", "cat", False)] * 4097, ValueError),
    ],
)
def test_native_batch_rejects_invalid_inputs(cases, error):
    with pytest.raises(error):
        quotes_observed(cases, backend="native")
    assert quotes_observed([("cat", "cat", False)], backend="native") == [True]


def test_native_maximum_and_threaded_independence():
    assert quotes_observed([("cat", "cat", False)] * 4096, backend="native") == [True] * 4096
    batches = [[("cat" if i % 2 else "cats", "cat", False)] for i in range(100)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda batch: quotes_observed(batch, backend="native"), batches))
    assert outputs == [[bool(i % 2)] for i in range(100)]


def test_native_batch_benchmark_records_binary_and_equal_outputs(tmp_path):
    path = tmp_path / "batch.json"
    main(
        [
            "--case",
            "quote_native",
            "--case",
            "quote_batch_native",
            "--rows",
            "140",
            "--repeats",
            "1",
            "--output",
            str(path),
        ]
    )
    report = json.loads(path.read_text())
    assert len(report["native_module_sha256"]) == 64
    scalar, batch = report["results"]
    assert scalar["output_sha256"] == batch["output_sha256"]
    assert scalar["correctness_checked"] and batch["correctness_checked"]


def test_batch_only_benchmark_identifies_native_binary(tmp_path):
    path = tmp_path / "batch-only.json"
    main(["--case", "quote_batch_native", "--rows", "2", "--repeats", "1", "--output", str(path)])
    report = json.loads(path.read_text())
    assert len(report["native_module_sha256"]) == 64
    assert report["results"][0]["correctness_checked"]
