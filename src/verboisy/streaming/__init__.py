# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public disk-backed dataset preparation and bounded record inspection."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from verboisy.streaming.api import stream_dataset
    from verboisy.streaming.contract import StreamLimits, StreamResult
    from verboisy.streaming.delta import UpdateLimits, UpdateResult
    from verboisy.streaming.ledger import StreamLedger
    from verboisy.streaming.quality import QualityReport, check_stream_quality
    from verboisy.streaming.update import stream_updates

__all__ = [
    "QualityReport",
    "StreamLedger",
    "StreamLimits",
    "StreamResult",
    "UpdateLimits",
    "UpdateResult",
    "check_stream_quality",
    "stream_dataset",
    "stream_updates",
]

_EXPORTS = {
    "QualityReport": "verboisy.streaming.quality",
    "StreamLedger": "verboisy.streaming.ledger",
    "StreamLimits": "verboisy.streaming.contract",
    "StreamResult": "verboisy.streaming.contract",
    "UpdateLimits": "verboisy.streaming.delta",
    "UpdateResult": "verboisy.streaming.delta",
    "check_stream_quality": "verboisy.streaming.quality",
    "stream_dataset": "verboisy.streaming.api",
    "stream_updates": "verboisy.streaming.update",
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
