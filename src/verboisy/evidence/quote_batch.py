# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded batch matching used by explicit native verification."""

import os
from collections.abc import Callable
from functools import lru_cache
from typing import cast

from verboisy.evidence.quote_match import (
    _load_native_export,
    python_quote_observed,
    regex_quote_observed,
)

QuoteInput = tuple[str, str, bool]
QuoteBatch = list[QuoteInput] | tuple[QuoteInput, ...]
MAX_QUOTE_BATCH = 4096


@lru_cache(maxsize=1)
def _load_native_batch() -> Callable[[QuoteBatch], list[bool]]:
    return cast(Callable[[QuoteBatch], list[bool]], _load_native_export("quotes_observed"))


def quotes_observed(cases: QuoteBatch, *, backend: str | None = None) -> list[bool]:
    """Return scalar-equivalent decisions in order, or fail without partial output."""
    selected = (
        backend if backend is not None else os.environ.get("VERBOISY_QUOTE_MATCHER", "python")
    )
    if selected == "native":
        return _load_native_batch()(cases)
    if selected not in ("python", "regex"):
        raise ValueError("VERBOISY_QUOTE_MATCHER must be python, regex or native")
    if type(cases) not in (list, tuple):
        raise TypeError("Quote batch must be a list or tuple")
    if len(cases) > MAX_QUOTE_BATCH:
        raise ValueError("Quote batch exceeds 4096 entries")
    matcher = python_quote_observed if selected == "python" else regex_quote_observed
    output = []
    for item in cases:
        if type(item) is not tuple or len(item) != 3:
            raise TypeError("Quote batch entries must be (text, quote, bool) tuples")
        text, quote, numeric = item
        if not isinstance(text, str) or not isinstance(quote, str) or not isinstance(numeric, bool):
            raise TypeError("Quote batch entries must contain two strings and a bool")
        output.append(matcher(text, quote, numeric))
    return output
