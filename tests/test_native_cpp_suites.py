# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Run assertions written in C++ against the linked production implementations."""

import hashlib
import importlib.util
import json
import sysconfig
from pathlib import Path

import pytest

pytestmark = pytest.mark.native
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cpp_suites():
    directory = ROOT / "build/native"
    path = directory / ("_verboisy_quote_native_tests" + sysconfig.get_config_var("EXT_SUFFIX"))
    if not path.is_file():
        pytest.skip("Build direct C++ tests with scripts/build_native_tests.py")
    # A stale suite could pass against yesterday's implementation. Require the
    # binary and all linked inputs to match the builder's current fingerprint.
    metadata = json.loads((directory / "quote-tests-build.json").read_text())
    assert metadata["purpose"] == "direct_cpp_tests"
    assert metadata["build_version"] == "1"
    assert metadata["module_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    inputs = {
        "native/quote_match.cpp",
        "native/quote_batch.cpp",
        "native/quote_batch.hpp",
        "native/tests/test_quote_batch.cpp",
        "native/unicode_boundaries.cpp",
        "native/quote_match.hpp",
        "native/unicode_boundaries.hpp",
        "native/tests/python_test_module.cpp",
        "native/tests/test_quote_match.cpp",
        "native/tests/test_unicode_boundaries.cpp",
        "native/tests/test_support.hpp",
    }
    assert set(metadata["source_hashes"]) == inputs
    for name in inputs:
        assert (
            metadata["source_hashes"][name]
            == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        )
    spec = importlib.util.spec_from_file_location("_verboisy_quote_native_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "suite,minimum", [("quote_match", 200), ("unicode_boundaries", 30), ("quote_batch", 8)]
)
def test_direct_cpp_suite(cpp_suites, suite, minimum):
    assert cpp_suites.run_suite(suite) >= minimum


def test_cpp_suites_can_repeat_in_one_interpreter(cpp_suites):
    first = [cpp_suites.run_suite(name) for name in ("quote_match", "unicode_boundaries")]
    second = [cpp_suites.run_suite(name) for name in ("quote_match", "unicode_boundaries")]
    assert second == first


def test_cpp_suite_unknown_name(cpp_suites):
    with pytest.raises(ValueError, match="Unknown native test suite"):
        cpp_suites.run_suite("unknown")


@pytest.mark.parametrize("arguments", [(), (None,), ("quote_match", "extra")])
def test_cpp_suite_argument_validation(cpp_suites, arguments):
    with pytest.raises(TypeError):
        cpp_suites.run_suite(*arguments)
