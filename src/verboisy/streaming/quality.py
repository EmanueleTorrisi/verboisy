# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check a completed streaming capture against a dataset quality contract."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verboisy.streaming.contract import StreamError
from verboisy.streaming.integrity import validated_job, verified_export_rows
from verboisy.streaming.ledger import StreamLedger
from verboisy.streaming.quality_checks import (
    CompletenessCheck,
    RowCountCheck,
    UniquenessCheck,
    _Row,
    assess,
)
from verboisy.streaming.quality_contract import (
    DEFAULT_INDEX_BYTES,
    compile_contract,
    validate_index_limit,
)


@dataclass(frozen=True)
class QualityReport:
    """Complete, value-free findings bound to the checked capture and contract."""

    job_id: str
    source_sha256: str
    source_bytes: int
    source_contract_sha256: str
    quality_contract_sha256: str
    passed: bool
    rows: int
    row_count: RowCountCheck
    completeness: tuple[CompletenessCheck, ...]
    uniqueness: tuple[UniquenessCheck, ...]
    report_version: str = "stream-quality-1"


def check_stream_quality(
    *,
    database: Path,
    job_id: str,
    contract: dict[str, Any],
    max_index_bytes: int = DEFAULT_INDEX_BYTES,
    scratch_dir: Path | None = None,
) -> QualityReport:
    """Return a report only after complete, read-only source replay.

    A version 1 contract accepts min_rows, max_rows, completeness rules with
    field and min_present_percent, and unique groups of field pointers.
    Completeness counts missing, null and whitespace-only strings separately.
    Keys use nonempty strings or integers without coercion. Pointers refer to
    the saved output records, including an explicitly configured projection.
    """
    policy = compile_contract(contract)
    ceiling = validate_index_limit(max_index_bytes)
    with closing(StreamLedger(database, read_only=True)) as ledger:
        try:
            ledger.connection.execute("BEGIN")
        except sqlite3.Error as error:
            raise StreamError("Cannot open a consistent streaming ledger snapshot") from error
        job = validated_job(ledger, job_id)
        if job["status"] != "COMPLETED":
            raise StreamError("Dataset quality requires a completed streaming job")
        if job["_contract"]["format"] == "asset":
            raise StreamError("Opaque assets do not have dataset quality rows")
        needs_values = bool(policy.completeness or policy.unique)
        with closing(verified_export_rows(ledger, job)) as replay:
            result = assess(
                (
                    _Row(
                        source.row_index,
                        source.line_start,
                        source.line_end,
                        json.loads(output) if needs_values else {},
                    )
                    for source, output in replay
                ),
                policy,
                expected_rows=job["processed"],
                folder=scratch_dir if scratch_dir is not None else ledger.path.parent,
                max_index_bytes=ceiling,
            )
        saved = json.dumps(
            job["_contract"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return QualityReport(
            job_id,
            job["sha256"],
            job["byte_count"],
            hashlib.sha256(saved).hexdigest(),
            policy.sha256,
            result.passed,
            result.rows,
            result.row_count,
            result.completeness,
            result.uniqueness,
        )
