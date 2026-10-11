# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Batch boundaries and failures must agree with independent scalar matching."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from verboisy.evidence import quote_batch, quote_match

from benchmarks.runner import main
from benchmarks.workloads import quote_cases
from tests.test_quote_match import CASES, generated_cases


@pytest.mark.parametrize("backend", ["python", "regex"])
def test_batches_match_scalar_unicode_reference(backend):
    cases = [(text, quote, numeric) for text, quote, numeric, _ in [*CASES, *quote_cases(15)]]
    cases.extend(generated_cases())
    for start in range(0, len(cases), 1024):
        chunk = cases[start : start + 1024]
        expected = [quote_match.regex_quote_observed(*case) for case in chunk]
        assert quote_batch.quotes_observed(chunk, backend=backend) == expected
    assert quote_batch.quotes_observed((), backend=backend) == []
    assert quote_batch.quotes_observed((("cat", "cat", False),), backend=backend) == [True]


@pytest.mark.parametrize("backend", ["python", "regex"])
@pytest.mark.parametrize(
    "cases",
    [
        None,
        "cat",
        iter([]),
        [None],
        [["cat", "cat", False]],
        [("cat",)],
        [("cat", "cat", False), (None, "cat", False)],
        [("cat", None, False)],
        [("cat", "cat", 1)],
        [("cat", "cat", None)],
    ],
)
def test_invalid_batch_has_no_partial_result(backend, cases):
    with pytest.raises(TypeError):
        quote_batch.quotes_observed(cases, backend=backend)


@pytest.mark.parametrize("backend", ["python", "regex"])
def test_batch_limit_and_no_result_cache(backend):
    cases = [("cat", "cat", False)] * 4096
    assert quote_batch.quotes_observed(cases, backend=backend) == [True] * 4096
    cases.append(("cat", "cat", False))
    with pytest.raises(ValueError, match="4096"):
        quote_batch.quotes_observed(cases, backend=backend)
    cases[:] = [("cats", "cat", False)]
    assert quote_batch.quotes_observed(cases, backend=backend) == [False]


def test_default_environment_and_invalid_backend(monkeypatch):
    monkeypatch.delenv("VERBOISY_QUOTE_MATCHER", raising=False)
    assert quote_batch.quotes_observed([("cat", "cat", False)]) == [True]
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "regex")
    assert quote_batch.quotes_observed([("cats", "cat", False)]) == [False]
    with pytest.raises(ValueError, match="must be python, regex or native"):
        quote_batch.quotes_observed([], backend="invalid")


def test_batch_loader_caches_function_without_caching_results(monkeypatch):
    quote_batch._load_native_batch.cache_clear()
    matching = Mock(side_effect=[[True], [False]])
    monkeypatch.setattr(quote_batch, "_load_native_export", lambda _name: matching)
    try:
        assert quote_batch.quotes_observed([("cat", "cat", False)], backend="native") == [True]
        assert quote_batch.quotes_observed([("cats", "cat", False)], backend="native") == [False]
        assert quote_batch._load_native_batch.cache_info().hits == 1
        assert matching.call_count == 2
    finally:
        quote_batch._load_native_batch.cache_clear()


def test_outdated_native_export_reports_rebuild(monkeypatch):
    monkeypatch.setattr(
        quote_match.importlib.util, "module_from_spec", lambda _spec: SimpleNamespace()
    )
    monkeypatch.setattr(
        quote_match.importlib.machinery.ExtensionFileLoader,
        "exec_module",
        lambda _self, _module: None,
    )
    with pytest.raises(RuntimeError, match="outdated; rebuild"):
        quote_match._load_native_export("quotes_observed")


def test_missing_batch_binary_keeps_python_available(tmp_path, monkeypatch):
    quote_batch._load_native_batch.cache_clear()
    monkeypatch.setenv("VERBOISY_NATIVE_QUOTE_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="Native quote matcher unavailable"):
        quote_batch.quotes_observed([], backend="native")
    assert quote_batch.quotes_observed([("cat", "cat", False)], backend="python") == [True]


def test_python_batch_benchmark_has_checked_scalar_digest(tmp_path):
    import json

    path = tmp_path / "batch.json"
    main(
        [
            "--case",
            "quote_python",
            "--case",
            "quote_batch_python",
            "--rows",
            "140",
            "--repeats",
            "1",
            "--output",
            str(path),
        ]
    )
    report = json.loads(path.read_text())
    scalar, batch = report["results"]
    assert scalar["output_sha256"] == batch["output_sha256"]
    assert scalar["correctness_checked"] and batch["correctness_checked"]
