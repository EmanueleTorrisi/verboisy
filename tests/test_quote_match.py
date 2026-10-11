# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal search must preserve the verifier's former regex decisions."""

import random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from verboisy.evidence import quote_match

from benchmarks.workloads import quote_cases

CASES = [
    ("", "", False, False),
    ("abc", "", False, False),
    ("", "abc", False, False),
    ("a!!!", "!!", False, True),
    ("XcatY; cat", "cat", False, True),
    ("XcatY", "cat", False, False),
    ("cat_", "cat", False, False),
    ("A\u0301", "A", False, True),
    ("cat\u200b", "cat", False, True),
    ("\x00cat\x00", "cat", False, True),
    ("\ud800cat\udfff", "cat", False, True),
    ("犬", "犬", False, True),
    ("犬猫", "犬", False, False),
    ("𐐀cat", "cat", False, False),
    ("Ⅻcat", "cat", False, False),
    ("4.\u0665", "4", True, False),
    ("4.²", "4", True, True),
    ("4²", "4", True, False),
    ("4, people", "4", True, True),
    ("4,5", "4", True, False),
    ("-4", "4", True, False),
    ("\u22124", "4", True, False),
    ("+4", "4", True, False),
    (".4", "4", True, False),
    (",4", "4", True, False),
    ("(-4)", "-4", True, True),
    ("X[x]Y; [x]", "[x]", False, True),
    ("x", "[x]", False, False),
    ("a+b", "a+b", False, True),
]


def generated_cases():
    randomizer = random.Random(71023)
    alphabet = "a_4.,+-! []()" + "李犬é²Ⅻ\u0301\u0665\u2212\x00\ud800𐐀"
    for _ in range(6000):
        quote = "".join(randomizer.choices(alphabet, k=randomizer.randrange(5)))
        text = "".join(randomizer.choices(alphabet, k=randomizer.randrange(18)))
        if randomizer.randrange(2):
            text += quote
        yield text, quote, bool(randomizer.randrange(2))
    # Sweep distinct Unicode blocks as surrounding characters, including
    # astral and surrogate code points, rather than only ASCII-heavy samples.
    for codepoint in range(0, 0x110000, 113):
        character = chr(codepoint)
        yield character + "Q", "Q", False
        yield "4." + character, "4", True


def test_python_reference_matches_regex_with_unicode_and_overlaps():
    for text, quote, numeric, expected in [*CASES, *quote_cases(12)]:
        assert quote_match.regex_quote_observed(text, quote, numeric) is expected
        assert quote_match.python_quote_observed(text, quote, numeric) is expected
    for text, quote, numeric in generated_cases():
        assert quote_match.python_quote_observed(text, quote, numeric) == (
            quote_match.regex_quote_observed(text, quote, numeric)
        )


@pytest.mark.parametrize("backend", ["python", "regex"])
def test_explicit_and_environment_selection(monkeypatch, backend):
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", backend)
    assert quote_match.quote_observed("cat", "cat") is True
    assert quote_match.quote_observed("cat", "cat", backend=backend) is True


def test_default_selection_and_invalid_backend(monkeypatch):
    monkeypatch.delenv("VERBOISY_QUOTE_MATCHER", raising=False)
    assert quote_match.quote_observed("cat", "cat") is True
    with pytest.raises(ValueError, match="must be python, regex or native"):
        quote_match.quote_observed("cat", "cat", backend="invalid")


def test_missing_native_build_is_explicit_and_python_still_works(tmp_path, monkeypatch):
    quote_match._load_native.cache_clear()
    monkeypatch.setenv("VERBOISY_NATIVE_QUOTE_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="Native quote matcher unavailable"):
        quote_match.quote_observed("cat", "cat", backend="native")
    assert quote_match.quote_observed("cat", "cat", backend="python") is True


def test_optional_loader_reuses_success_without_caching_match_outcomes(monkeypatch):
    quote_match._load_native.cache_clear()
    matching = Mock(side_effect=[True, False])
    module = SimpleNamespace(quote_observed=matching)
    monkeypatch.setattr(quote_match.importlib.util, "module_from_spec", lambda _spec: module)
    execute = Mock()
    monkeypatch.setattr(quote_match.importlib.machinery.ExtensionFileLoader, "exec_module", execute)
    try:
        assert quote_match.quote_observed("cat", "cat", backend="native") is True
        assert quote_match.quote_observed("XcatY", "cat", backend="native") is False
        assert execute.call_count == 1
        assert matching.call_args_list[0].args == ("cat", "cat", False)
        assert matching.call_args_list[1].args == ("XcatY", "cat", False)
    finally:
        quote_match._load_native.cache_clear()


def test_native_directory_must_be_absolute(monkeypatch):
    quote_match._load_native.cache_clear()
    monkeypatch.setenv("VERBOISY_NATIVE_QUOTE_DIR", "relative-directory")
    with pytest.raises(ValueError, match="must be an absolute directory"):
        quote_match.quote_observed("cat", "cat", backend="native")


def test_long_repeated_literals_and_embedded_overlaps():
    for text, quote, numeric in [
        ("a" * 20000, "a" * 10000, False),
        ("a" * 20000 + "; " + "a" * 10000, "a" * 10000, False),
        ("+" * 20000 + "4", "+4", True),
        ("a!!!", "!!", False),
    ]:
        assert quote_match.python_quote_observed(text, quote, numeric) == (
            quote_match.regex_quote_observed(text, quote, numeric)
        )
