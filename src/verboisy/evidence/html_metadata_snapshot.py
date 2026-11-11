# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bind explicit metadata observations to ordinary replayable field proofs."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from verboisy.evidence.html_metadata import (
    MAX_TEXT_CHARS,
    HtmlMetadataError,
    HtmlMetadataSpec,
    literal_metadata,
)
from verboisy.evidence.models import Candidate, Proof, Snapshot, Source

_SCOPE = "html-metadata"


def html_metadata_snapshot(html: str, url: str, max_chars: int, plan: HtmlMetadataSpec) -> Snapshot:
    values = literal_metadata(html, plan)
    sources = [
        Source(id=f"m{index}", kind="text", text=value if value is not None else "", scope=_SCOPE)
        for index, (_, value) in enumerate(sorted(values.items()))
    ]
    if sum(len(source.model_dump_json()) for source in sources) > max_chars:
        raise HtmlMetadataError("metadata_evidence_limit")
    content_hash = hashlib.sha256(html.encode()).hexdigest()
    fetched_at = datetime.now(UTC).isoformat()
    sid = hashlib.sha256((url + fetched_at + content_hash).encode()).hexdigest()
    return Snapshot(
        id=sid,
        url=url,
        fetched_at=fetched_at,
        content_hash=content_hash,
        sources=sources,
        truncated=False,
    )


def html_metadata_candidate(page: Snapshot, plan: HtmlMetadataSpec) -> Candidate:
    """Replay typed field values solely from the captured binding IDs."""
    if page.truncated or any(
        value is not None
        for value in (
            page.dataset_asset_id,
            page.dataset_row_index,
            page.dataset_projection,
            page.dataset_source_row_json,
        )
    ):
        raise HtmlMetadataError("invalid_metadata_snapshot")
    sources = {source.id: source for source in page.sources}
    fields = sorted(plan.fields.items())
    if len(sources) != len(page.sources) or sources.keys() != {f"m{i}" for i in range(len(fields))}:
        raise HtmlMetadataError("invalid_metadata_sources")
    record: dict[str, str | None] = {}
    evidence: dict[str, Proof] = {}
    for index, (name, binding) in enumerate(fields):
        source = sources[f"m{index}"]
        if (
            source.scope != _SCOPE
            or source.kind != "text"
            or source.href is not None
            or len(source.text) > MAX_TEXT_CHARS
            or source.text != " ".join(source.text.split())
        ):
            raise HtmlMetadataError("invalid_metadata_source")
        # A captured empty slot means the binding was absent, never a blank matched value.
        if not source.text:
            if binding.on_missing != "null":
                raise HtmlMetadataError("required_field_missing")
            record[name] = None
            continue
        record[name] = source.text
        evidence["/" + name] = Proof(source=source.id, quote=source.text, transform="text")
    return Candidate(scope=_SCOPE, record=record, evidence=evidence)
