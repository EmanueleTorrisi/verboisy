# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bind declared table cells to stable row scopes and replayable field proofs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from verboisy.evidence.html_table import (
    HtmlTableError,
    HtmlTableSpec,
    literal_table_rows,
    table_value,
)
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source

_SCOPE = "html-table-row-"
_INDEX = re.compile(r"(?:0|[1-9][0-9]?)")
# Bound the compact snapshot payload repeated by the portable research format.
MAX_PORTABLE_SNAPSHOT_BYTES = 8 * 1024**2


def _source_id(row: int, column: int) -> str:
    return f"t{row}c{column}"


def _snapshot_id(
    url: str, stamp: str, content_hash: str, plan: HtmlTableSpec, sources: list[Source]
) -> str:
    binding = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    identity = f"html-table-v1\n{url}\n{stamp}\n{content_hash}\n{binding}"
    digest = hashlib.sha256(identity.encode())
    for source in sources:
        digest.update(b"\n")
        values = [source.id, source.kind, source.text, source.scope, source.href]
        digest.update(json.dumps(values, separators=(",", ":")).encode())
    return digest.hexdigest()


def html_table_snapshot(html: str, url: str, max_chars: int, plan: HtmlTableSpec) -> Snapshot:
    rows = literal_table_rows(html, plan)
    sources = [
        Source(id=_source_id(row, column), kind="text", text=text, scope=_SCOPE + str(row))
        for row, cells in enumerate(rows)
        for column, text in enumerate(cells)
    ]
    content_hash = hashlib.sha256(html.encode()).hexdigest()
    fetched_at = datetime.now(UTC).isoformat()
    page = Snapshot(
        id=_snapshot_id(url, fetched_at, content_hash, plan, sources),
        url=url,
        fetched_at=fetched_at,
        content_hash=content_hash,
        sources=sources,
        truncated=False,
    )
    serialized = page.model_dump_json()
    if (
        len(serialized) > max_chars
        or len(serialized.encode()) * len(rows) > MAX_PORTABLE_SNAPSHOT_BYTES
    ):
        raise HtmlTableError("table_evidence_limit")
    return page


def _validate_snapshot(page: Snapshot, plan: HtmlTableSpec) -> None:
    if (
        page.truncated
        or len(page.sources) != len(plan.keys) * len(plan.fields)
        or any(
            value is not None
            for value in (
                page.dataset_asset_id,
                page.dataset_row_index,
                page.dataset_projection,
                page.dataset_source_row_json,
            )
        )
        or page.id != _snapshot_id(page.url, page.fetched_at, page.content_hash, plan, page.sources)
    ):
        raise HtmlTableError("invalid_table_snapshot")


def _candidate(page: Snapshot, plan: HtmlTableSpec, row: int) -> Candidate:
    scope = _SCOPE + str(row)
    fields = sorted(plan.fields.items())
    width = len(fields)
    record: dict[str, str | int] = {}
    evidence: dict[str, Proof] = {}
    for column, (name, binding) in enumerate(fields):
        source = page.sources[row * width + column]
        if (
            source.scope != scope
            or source.id != _source_id(row, column)
            or source.kind != "text"
            or source.href is not None
        ):
            raise HtmlTableError("invalid_table_source")
        record[name] = table_value(source.text, binding)
        evidence["/" + name] = Proof(
            source=source.id, quote=source.text, transform=binding.value_type
        )
    if record[plan.key_field] != plan.keys[row]:
        raise HtmlTableError("table_key_binding_mismatch")
    return Candidate(scope=scope, record=record, evidence=evidence)


def html_table_candidate(page: Snapshot, plan: HtmlTableSpec, scope: str) -> Candidate:
    """Read the captured cells for one key and validate their snapshot binding."""
    index_text = scope.removeprefix(_SCOPE)
    if not scope.startswith(_SCOPE) or _INDEX.fullmatch(index_text) is None:
        raise HtmlTableError("invalid_table_scope")
    row = int(index_text)
    if row >= len(plan.keys):
        raise HtmlTableError("invalid_table_scope")
    _validate_snapshot(page, plan)
    return _candidate(page, plan, row)


def html_table_candidates(page: Snapshot, plan: HtmlTableSpec) -> list[Candidate]:
    """Replay all declared rows with one snapshot integrity check."""
    _validate_snapshot(page, plan)
    return [_candidate(page, plan, index) for index in range(len(plan.keys))]


def same_table_candidate(expected: Candidate | None, actual: Candidate) -> bool:
    """Require identical proofs and exact scalar types, including integer versus bool."""
    return (
        expected is not None
        and expected == actual
        and all(
            value.__class__ is actual.record[name].__class__
            for name, value in expected.record.items()
        )
    )
