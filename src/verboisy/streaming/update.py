# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Generate incremental changes from two completed captures in a streaming ledger."""

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import closing
from pathlib import Path
from typing import Any

from verboisy.storage.path_safety import local_source_paths, validate_output_paths
from verboisy.streaming.contract import StreamError
from verboisy.streaming.delta import (
    UpdateLimits,
    UpdateResult,
    _json,
    _Record,
    _Version,
    _write_delta,
)
from verboisy.streaming.integrity import validated_job, verified_export_rows
from verboisy.streaming.ledger import StreamLedger


def _records(ledger: StreamLedger, job: dict[str, Any]) -> Generator[_Record, None, None]:
    with closing(verified_export_rows(ledger, job)) as rows:
        for source, output in rows:
            # The verifier returns the replayed, strictly validated object.
            yield _Record(source.row_index, source.line_start, source.line_end, json.loads(output))


def _signature(contract: dict[str, Any]) -> bytes:
    return _json({name: contract.get(name) for name in ("format", "schema", "projection")})


def _protect(ledger: StreamLedger, output: Path, *contracts: dict[str, Any]) -> None:
    protected = {
        Path(str(ledger.path) + suffix) for suffix in ("", ".lock", "-journal", "-wal", "-shm")
    }
    protected.add(Path(".env").resolve())
    protected.update(local_source_paths(contract["source_uri"] for contract in contracts))
    for contract in contracts:
        protected.update(Path(path) for path in contract.get("protected_inputs", ()))
    try:
        validate_output_paths((output,), protected)
    except (OSError, ValueError) as error:
        raise StreamError(
            "Streaming update destination aliases a protected or unsafe path"
        ) from error


def stream_updates(
    *,
    database: Path,
    baseline: str,
    current: str,
    keys: tuple[str, ...],
    output: Path,
    complete_snapshot: bool = False,
    limits: UpdateLimits | None = None,
) -> UpdateResult:
    """Write a new JSONL patch, leaving the ledger and original snapshots intact.

    Both jobs must replay to completion under the same format, schema and
    projection. Keys are object-field JSON pointers in the output records;
    their nonempty string and integer values are matched without coercion.
    Set complete_snapshot only when both captures cover the same full dataset.
    Otherwise absent baseline keys are counted without emitting deletions.
    """
    if baseline == current:
        raise StreamError("Choose two distinct streaming jobs")
    if not isinstance(complete_snapshot, bool):
        raise StreamError("Complete snapshot must be an explicit boolean")
    if output.suffix.lower() != ".jsonl" or output.exists():
        raise StreamError("Choose a new .jsonl file for the streaming update")
    with closing(StreamLedger(database, read_only=True)) as ledger:
        try:
            # One read transaction binds both replays to a coherent ledger view.
            ledger.connection.execute("BEGIN")
        except sqlite3.Error as error:
            raise StreamError("Cannot open a consistent streaming ledger snapshot") from error
        before, after = (validated_job(ledger, job) for job in (baseline, current))
        if any(job["status"] != "COMPLETED" for job in (before, after)):
            raise StreamError("Streaming updates require two completed jobs")
        old, new = before["_contract"], after["_contract"]
        if any(contract["format"] == "asset" for contract in (old, new)):
            raise StreamError("Opaque asset captures do not have comparable records")
        signature = _signature(old)
        if signature != _signature(new):
            raise StreamError("Streaming update jobs must share a format, schema and projection")
        _protect(ledger, output, old, new)
        with closing(_records(ledger, before)) as older, closing(_records(ledger, after)) as newer:
            return _write_delta(
                _Version(baseline, before["sha256"], before["processed"], older),
                _Version(current, after["sha256"], after["processed"], newer),
                keys=keys,
                contract_sha256=hashlib.sha256(signature).hexdigest(),
                output=output,
                complete_snapshot=complete_snapshot,
                limits=limits or UpdateLimits(),
            )
