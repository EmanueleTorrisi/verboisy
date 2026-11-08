# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public disk-backed dataset preparation and bounded record inspection."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from verboisy.streaming.api import stream_dataset
    from verboisy.streaming.contract import StreamLimits, StreamResult
    from verboisy.streaming.ledger import StreamLedger

__all__ = ["StreamLedger", "StreamLimits", "StreamResult", "stream_dataset"]

_EXPORTS = {
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
