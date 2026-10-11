# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Execute the actual compiled extension, separately from optional-loader mocks."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.quote_match import native_module_path, quote_observed, regex_quote_observed
from verboisy.evidence.verify import verify

from benchmarks.runner import main
from benchmarks.workloads import SCHEMA, evidence, quote_cases, records
from tests.test_quote_match import CASES, generated_cases

pytestmark = pytest.mark.native


@pytest.fixture(autouse=True)
def compiled_extension():
    if not native_module_path().is_file():
        pytest.skip("Build the optional extension with scripts/build_native.py")


def test_native_matches_regex_and_python_across_unicode_cases():
    for text, quote, numeric, expected in [*CASES, *quote_cases(100)]:
        assert quote_observed(text, quote, numeric, backend="native") is expected
    for text, quote, numeric in generated_cases():
        assert quote_observed(text, quote, numeric, backend="native") == regex_quote_observed(
            text, quote, numeric
        )


def test_native_argument_errors():
    with pytest.raises(TypeError):
        quote_observed(None, "cat", backend="native")
    with pytest.raises(TypeError):
        quote_observed("cat", None, backend="native")


def test_native_verifier_preserves_full_errors(monkeypatch):
    page, candidate = evidence(records(1)[0], 0)
    invalid = candidate.model_copy(deep=True)
    invalid.evidence["/name"].quote = "unobserved"
    missing = candidate.model_copy(deep=True)
    missing.evidence.pop("/amount")
    outside = candidate.model_copy(deep=True)
    outside.scope = "outside"
    task = TaskSpec(identity_fields=["/name"])
    results = []
    for backend in ("regex", "python", "native"):
        monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", backend)
        results.append(
            [verify(c, page, SCHEMA, task) for c in [candidate, invalid, missing, outside]]
        )
    assert results[0] == results[1] == results[2]
    assert results[0][0] == []
    assert all(results[0][index] for index in (1, 2, 3))


def test_native_threaded_calls_do_not_share_matching_state():
    cases = quote_cases(50)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda case: quote_observed(*case[:3], backend="native"), cases))
    assert results == [case[3] for case in cases]


def test_native_benchmark_records_compiled_binary_identity(tmp_path):
    import json

    output = tmp_path / "native.json"
    main(["--case", "quote_native", "--rows", "12", "--repeats", "1", "--output", str(output)])
    report = json.loads(output.read_text())
    assert len(report["native_module_sha256"]) == 64
    assert report["results"][0]["correctness_checked"] is True
    assert report["quote_fixture_sha256"] is not None
    native_sources = {name for name in report["source_hashes"] if name.startswith("native/")}
    assert native_sources == {
        "native/python_module.cpp",
        "native/quote_match.cpp",
        "native/quote_batch.cpp",
        "native/quote_batch.hpp",
        "native/quote_match.hpp",
        "native/unicode_boundaries.cpp",
        "native/unicode_boundaries.hpp",
    }
    # The build report must identify the same inputs as the benchmark report.
    metadata = json.loads((native_module_path().parent / "quote-build.json").read_text())
    assert metadata["build_version"] == "2"
    assert metadata["source_hashes"] == {
        name: report["source_hashes"][name] for name in native_sources
    }
    assert metadata["module_sha256"] == report["native_module_sha256"]


def test_native_long_repeated_literals():
    for text, quote, numeric in [
        ("a" * 20000, "a" * 10000, False),
        ("a" * 20000 + "; " + "a" * 10000, "a" * 10000, False),
        ("+" * 20000 + "4", "+4", True),
    ]:
        assert quote_observed(text, quote, numeric, backend="native") == regex_quote_observed(
            text, quote, numeric
        )
