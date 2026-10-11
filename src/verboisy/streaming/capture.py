# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Capture explicitly granted local files without a full-file buffer or single large BLOB."""

import hashlib
import io
import os
import stat
from pathlib import Path
from typing import Any

from verboisy.streaming.contract import CHUNK_BYTES, StreamError, StreamLimits
from verboisy.streaming.ledger import ChunkReader, StreamLedger
from verboisy.utils.config import Settings


def capture_file(
    ledger: StreamLedger, job_id: str, source: Path, config: Settings, limits: StreamLimits
) -> None:
    resolved = source.resolve(strict=True)
    roots = [Path(root).resolve(strict=True) for root in config.dataset_local_roots]
    if not any(resolved.is_relative_to(root) and root.is_dir() for root in roots):
        raise StreamError("Streaming source is outside DATASET_LOCAL_ROOTS")
    expected = resolved.stat()
    if not stat.S_ISREG(expected.st_mode):
        raise StreamError("Streaming source must be a regular file")
    if expected.st_size > limits.max_input_bytes:
        raise StreamError("Streaming input byte limit exceeded")
    db = ledger.connection
    # Partial acquisition has admitted no rows. Reacquire it explicitly on resume;
    # completed capture is immutable and never consults the original file again.
    with db:
        db.execute("DELETE FROM stream_chunks WHERE job_id=?", (job_id,))
    count, sequence = 0, 0
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise StreamError("Streaming source changed before capture")
        while content := stream.read(CHUNK_BYTES):
            count += len(content)
            if count > limits.max_input_bytes:
                raise StreamError("Streaming input byte limit exceeded")
            digest.update(content)
            with db:
                db.execute(
                    "INSERT INTO stream_chunks VALUES(?,?,?,?)",
                    (job_id, sequence, hashlib.sha256(content).hexdigest(), content),
                )
            sequence += 1
        finished = os.fstat(stream.fileno())
    if (opened.st_size, opened.st_mtime_ns) != (
        finished.st_size,
        finished.st_mtime_ns,
    ) or count != finished.st_size:
        raise StreamError("Streaming source changed during capture")
    with db:
        db.execute(
            "UPDATE stream_jobs SET captured=1,byte_count=?,sha256=? WHERE id=?",
            (count, digest.hexdigest(), job_id),
        )


def verify_capture(ledger: StreamLedger, job: dict[str, Any]) -> None:
    """Verify every chunk before any new row can be admitted or export published."""
    with io.BufferedReader(ChunkReader(ledger, job), buffer_size=CHUNK_BYTES) as stream:
        while stream.read(CHUNK_BYTES):
            pass
