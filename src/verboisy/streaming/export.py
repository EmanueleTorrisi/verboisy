# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Streaming portable bundles; verified staged files publish their manifest last."""

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import SourceRow
from verboisy.storage.exporters import _csv_value, sync_directory
from verboisy.storage.path_safety import validate_output_paths
from verboisy.streaming.capture import verify_capture
from verboisy.streaming.contract import CHUNK_BYTES, StreamError
from verboisy.streaming.integrity import (
    validated_job,
    verified_export_rows,
)
from verboisy.streaming.ledger import ChunkReader, StreamLedger


def bundle_paths(output: Path) -> tuple[Path, Path, Path, Path]:
    return (
        output,
        output.with_name(output.name + ".evidence.jsonl"),
        output.with_name(output.name + ".source.bin"),
        output.with_name(output.name + ".manifest.json"),
    )


def export_stream(
    ledger: StreamLedger,
    job: dict[str, Any],
    output: Path,
    *,
    protected_inputs: tuple[Path, ...] = (),
) -> Path:
    if job["status"] != "COMPLETED":
        raise StreamError("Only completed streaming jobs can publish an export")
    if output.suffix.lower() not in {".jsonl", ".json", ".csv"}:
        raise StreamError("Streaming export requires .jsonl, .json or .csv")
    job = validated_job(ledger, job["id"])
    contract = job["_contract"]
    plan = (
        ProjectionPlan.model_validate(contract["projection"])
        if contract["projection"] is not None
        else None
    )
    targets = bundle_paths(output)
    protected = {
        *(Path(str(ledger.path) + suffix) for suffix in ("", ".lock", "-wal", "-shm", "-journal")),
        Path(url2pathname(urlsplit(contract["source_uri"]).path)).resolve(),
        Path(".env").resolve(),
        *(Path(path) for path in contract.get("protected_inputs", [])),
        *protected_inputs,
    }
    try:
        validate_output_paths(targets, protected)
    except (OSError, ValueError) as error:
        raise StreamError("Streaming output would overwrite a protected or unsafe path") from error
    verify_capture(ledger, job)
    with tempfile.TemporaryDirectory(prefix=".verboisy-stream-", dir=output.parent) as temp:
        stage = tuple(Path(temp) / path.name for path in targets)
        _write_rows(
            ledger,
            job,
            plan,
            stage[0],
            stage[1],
            contract["limits"]["max_record_bytes"],
            contract.get("csv_mode", "spreadsheet"),
        )
        with (
            stage[2].open("wb") as destination,
            io.BufferedReader(ChunkReader(ledger, job)) as source,
        ):
            while chunk := source.read(CHUNK_BYTES):
                destination.write(chunk)
        files = {path.name: _digest(path) for path in stage[:3]}
        manifest = {
            "manifest_version": "stream-1",
            "job_id": job["id"],
            "status": job["status"],
            "row_count": job["processed"],
            "source_sha256": job["sha256"],
            "source_bytes": job["byte_count"],
            "source_format": contract["format"],
            "source_uri": contract["source_uri"],
            "schema": contract["schema"],
            "projection": contract["projection"],
            "files": files,
            "output_values": "observed_or_explicitly_projected",
            "csv_mode": contract.get("csv_mode", "spreadsheet"),
            "csv_encoding": "JSON headers and cells"
            if contract.get("csv_mode") == "json"
            else "formula-capable strings prefixed with apostrophe",
            "row_identity": "physical_source_row",
            "truth_verified": False,
            "global_completeness_claimed": False,
        }
        stage[3].write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for staged in stage:
            with staged.open("r+b") as stream:
                os.fsync(stream.fileno())
        sync_directory(Path(temp))
        # A failed replacement must leave no stale manifest certifying mixed files.
        targets[3].unlink(missing_ok=True)
        sync_directory(output.parent)
        for saved, target in zip(stage, targets, strict=True):
            saved.replace(target)
            sync_directory(output.parent)
    return targets[3]


def _write_rows(
    ledger: StreamLedger,
    job: dict[str, Any],
    plan: ProjectionPlan | None,
    output: Path,
    evidence: Path,
    ceiling: int,
    csv_mode: str = "spreadsheet",
) -> None:
    _ = plan, ceiling
    headers: list[str] | None = None
    count = 0
    suffix = output.suffix.lower()
    with (
        output.open("w", encoding="utf-8", newline="") as data,
        evidence.open("w", encoding="utf-8") as proofs,
    ):
        writer = csv.writer(data)
        if suffix == ".json":
            data.write("[")
        rows = verified_export_rows(ledger, job)
        try:
            for source, value in rows:
                if suffix == ".csv":
                    record = json.loads(value)
                    if headers is None:
                        headers = list(record)
                        writer.writerow(
                            [
                                json.dumps(key, ensure_ascii=False)
                                if csv_mode == "json"
                                else _csv_value(key)
                                for key in headers
                            ]
                        )
                    if set(record) != set(headers) or any(
                        isinstance(v, dict | list) for v in record.values()
                    ):
                        raise StreamError("CSV streaming export requires stable flat columns")
                    writer.writerow(
                        [
                            json.dumps(record[key], ensure_ascii=False, allow_nan=False)
                            if csv_mode == "json"
                            else _csv_value(record[key])
                            for key in headers
                        ]
                    )
                elif suffix == ".json":
                    data.write(("," if count else "") + value)
                else:
                    data.write(value + "\n")
                count += 1
                proofs.write(_proof_line(source, value, job["id"], count))
            if suffix == ".json":
                data.write("]\n")
        finally:
            rows.close()


def _proof_line(source: SourceRow, value: str, job_id: str, output_row: int) -> str:
    """Serialize a row yielded by verified_export_rows, using its verified JSON.

    The replay iterator validates source bytes, saved values, projection, schema
    and row coordinates before yielding. Reuse those canonical JSON fragments
    without decoding and re-encoding their nested values. This helper must not
    receive unverified database strings. EOF is still checked before publication.
    """
    metadata = {
        "output_row": output_row,
        "source_row": source.row_index,
        "record_id": hashlib.sha256(
            f"verboisy:stream:{job_id}:{source.row_index}".encode()
        ).hexdigest(),
        "line_start": source.line_start,
        "line_end": source.line_end,
    }
    prefix = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    prefix = prefix[:-1] + ',"source_values":' + source.values_json
    if value == source.values_json:
        return prefix + ',"output_is_source":true}\n'
    return prefix + ',"output_is_source":false,"output_values":' + value + "}\n"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
