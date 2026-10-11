# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal quote matching with the verifier's Unicode and numeric boundaries."""

import importlib.machinery
import importlib.util
import os
import re
import sysconfig
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import cast

_WORD_RUN = re.compile(r"\w+")
_NUMBER_RUN = re.compile(r"[\w.,+\u2212-]+")
_NATIVE_NAME = "_verboisy_quote_native" + str(sysconfig.get_config_var("EXT_SUFFIX"))
_DEFAULT_NATIVE_FILE = Path(__file__).resolve().parents[3] / "build/native" / _NATIVE_NAME


def _word(character: str) -> bool:
    return character == "_" or character.isalnum()


def python_quote_observed(text: str, quote: str, numeric: bool = False) -> bool:
    """Find a literal with exactly the old regex's surrounding-character rules."""
    size = str.__len__(text)
    length = str.__len__(quote)
    if not length:
        return False
    position = str.find(text, quote)
    while position >= 0:
        before = str.__getitem__(text, position - 1) if position else ""
        end = position + length
        after = str.__getitem__(text, end) if end < size else ""
        left_blocked = _word(before) or (numeric and before in ".,+\u2212-" and bool(before))
        right_blocked = _word(after) or (
            numeric
            and after in ".,"
            and bool(after)
            and end + 1 < size
            and str.__getitem__(text, end + 1).isdecimal()
        )
        if not left_blocked and not right_blocked:
            return True
        # Advance by one code point: overlapping occurrences must remain visible.
        start = position + 1
        # Skip positions whose preceding character is forbidden. The constant
        # character-class regex prevents repeated long-literal searches within
        # a single word, without compiling a pattern for each distinct quote.
        blocked_run = (_NUMBER_RUN if numeric else _WORD_RUN).match(text, position)
        if blocked_run is not None:
            start = blocked_run.end() + 1
        position = str.find(text, quote, start)
    return False


def regex_quote_observed(text: str, quote: str, numeric: bool = False) -> bool:
    """Retain the original regex as an independently executable reference."""
    boundary = (
        r"(?<![\w.,+\u2212-])" + re.escape(quote) + r"(?!\w|[.,]\d)"
        if numeric
        else r"(?<!\w)" + re.escape(quote) + r"(?!\w)"
    )
    return bool(quote and re.search(boundary, text))


def native_module_path(directory: str | None = None) -> Path:
    configured = os.environ.get("VERBOISY_NATIVE_QUOTE_DIR", "") if directory is None else directory
    return Path(configured) / _NATIVE_NAME if configured else _DEFAULT_NATIVE_FILE


def _load_native_export(export: str) -> object:
    directory = os.environ.get("VERBOISY_NATIVE_QUOTE_DIR", "")
    if directory and not Path(directory).is_absolute():
        raise ValueError("VERBOISY_NATIVE_QUOTE_DIR must be an absolute directory")
    name = "_verboisy_quote_native"
    path = str(native_module_path(directory).resolve())
    loader = importlib.machinery.ExtensionFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    try:
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "Native quote matcher unavailable. Build it with scripts/build_native.py "
            "for this interpreter, or use VERBOISY_QUOTE_MATCHER=python."
        ) from exc
    try:
        return getattr(module, export)
    except AttributeError as exc:
        raise RuntimeError(
            "Native quote matcher is outdated; rebuild with scripts/build_native.py"
        ) from exc


@lru_cache(maxsize=1)
def _load_native() -> Callable[[str, str, bool], bool]:
    return cast(Callable[[str, str, bool], bool], _load_native_export("quote_observed"))


def quote_observed(
    text: str, quote: str, numeric: bool = False, *, backend: str | None = None
) -> bool:
    """Select an explicit backend; native failures never silently change behavior."""
    selected = (
        backend if backend is not None else os.environ.get("VERBOISY_QUOTE_MATCHER", "python")
    )
    if selected == "python":
        return python_quote_observed(text, quote, numeric)
    if selected == "regex":
        return regex_quote_observed(text, quote, numeric)
    if selected == "native":
        return _load_native()(text, quote, numeric)
    raise ValueError("VERBOISY_QUOTE_MATCHER must be python, regex or native")
