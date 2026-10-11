# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Shared parser error without dependency on any individual format adapter."""

from verboisy.utils.exceptions import VerboisyError


class DatasetParseError(VerboisyError):
    """An asset cannot satisfy the explicitly declared parser contract."""
