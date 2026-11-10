# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verboisy: autonomous web research with validated, durable records."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

__version__ = "1.0.0"

if TYPE_CHECKING:
    from .api import RunResult, arun, run
    from .operations import operational_report
    from .streaming import StreamLedger, StreamLimits, StreamResult, stream_dataset

__all__ = [
    "RunResult",
    "StreamLedger",
    "StreamLimits",
    "StreamResult",
    "arun",
    "operational_report",
    "run",
    "stream_dataset",
]

_EXPORTS = {
    "RunResult": "verboisy.api",
    "arun": "verboisy.api",
    "operational_report": "verboisy.operations",
    "run": "verboisy.api",
    "StreamLedger": "verboisy.streaming.ledger",
    "StreamLimits": "verboisy.streaming.contract",
    "StreamResult": "verboisy.streaming.contract",
    "stream_dataset": "verboisy.streaming.api",
}

# Reload restores the same public bindings as a fresh import.
for _export_name in _EXPORTS:
    globals().pop(_export_name, None)
del _export_name


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
