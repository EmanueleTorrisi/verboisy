# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public disk-backed dataset preparation and bounded record inspection."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from verboisy.streaming.analytics import AnalyticalExport, export_stream_analytics
    from verboisy.streaming.analytics_verify import AnalyticsVerification, verify_stream_analytics
    from verboisy.streaming.api import stream_dataset
    from verboisy.streaming.contract import StreamLimits, StreamResult
    from verboisy.streaming.delta import UpdateLimits, UpdateResult
    from verboisy.streaming.ledger import StreamLedger
    from verboisy.streaming.quality import QualityReport, check_stream_quality
    from verboisy.streaming.segments import JSONLSegmentResult, SealedJSONL, prepare_jsonl_segments
    from verboisy.streaming.update import stream_updates

__all__ = [
    "AnalyticalExport",
    "AnalyticsVerification",
    "JSONLSegmentResult",
    "QualityReport",
    "SealedJSONL",
    "StreamLedger",
    "StreamLimits",
    "StreamResult",
    "UpdateLimits",
    "UpdateResult",
    "check_stream_quality",
    "export_stream_analytics",
    "prepare_jsonl_segments",
    "stream_dataset",
    "stream_updates",
    "verify_stream_analytics",
]

_EXPORTS = {
    "AnalyticalExport": "verboisy.streaming.analytics",
    "AnalyticsVerification": "verboisy.streaming.analytics_verify",
    "JSONLSegmentResult": "verboisy.streaming.segments",
    "QualityReport": "verboisy.streaming.quality",
    "SealedJSONL": "verboisy.streaming.segments",
    "StreamLedger": "verboisy.streaming.ledger",
    "StreamLimits": "verboisy.streaming.contract",
    "StreamResult": "verboisy.streaming.contract",
    "UpdateLimits": "verboisy.streaming.delta",
    "UpdateResult": "verboisy.streaming.delta",
    "check_stream_quality": "verboisy.streaming.quality",
    "export_stream_analytics": "verboisy.streaming.analytics",
    "prepare_jsonl_segments": "verboisy.streaming.segments",
    "stream_dataset": "verboisy.streaming.api",
    "stream_updates": "verboisy.streaming.update",
    "verify_stream_analytics": "verboisy.streaming.analytics_verify",
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
