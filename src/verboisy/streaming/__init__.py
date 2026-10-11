# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public disk-backed dataset preparation and bounded record inspection."""

from verboisy.streaming.api import stream_dataset
from verboisy.streaming.contract import StreamLimits, StreamResult
from verboisy.streaming.ledger import StreamLedger

__all__ = ["StreamLedger", "StreamLimits", "StreamResult", "stream_dataset"]
