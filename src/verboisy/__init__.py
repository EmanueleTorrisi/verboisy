# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verboisy: autonomous web research with validated, durable records."""

__version__ = "1.0.0"
from .api import RunResult, arun, run
from .streaming import StreamLedger, StreamLimits, StreamResult, stream_dataset

__all__ = [
    "RunResult",
    "StreamLedger",
    "StreamLimits",
    "StreamResult",
    "arun",
    "run",
    "stream_dataset",
]
