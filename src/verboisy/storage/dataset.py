# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Atomic dataset exports backed by persisted evidence and checksummed manifests."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, TextIO

from verboisy.evidence.models import TaskSpec
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.presentation import PresentationPreferences
from verboisy.storage.asset_bundle import asset_bundle
from verboisy.storage.event_journal import reserved_attempt_ids
from verboisy.storage.exporters import _atomic_write, _csv_value
from verboisy.storage.lineage import build_cell_lineage
from verboisy.storage.research import ResearchStore


def export_dataset(
    store: ResearchStore,
    rid: str,
    destination: Path,
    schema: dict[str, Any],
    task: TaskSpec,
    *,
    rows: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    output_lineage: list[dict[str, Any]] | None = None,
    dataset_consistency: dict[str, Any] | None = None,
    presentation: PresentationPreferences | None = None,
) -> Path:
    """Write a generation atomically and commit it by writing the manifest last."""

    # Validate the proof chain before removing the old manifest or replacing data,
    # including exports whose public rows were supplied by the caller.
    captured_evidence = store.evidence(rid)
    captured_events = store.events(rid)
    search_events = [event for event in captured_events if event["kind"] == "search_request"]
    search_attempts = {
        provider: len(reserved_attempt_ids(search_events, provider=provider))
        for provider in ("openai", "brave")
    }
    state = store.load(rid)
    output_rows = rows if rows is not None else store.records(rid)
    if rows is None:
        output_lineage = [
            {"output_id": row["id"], "record_id": str(row["id"])} for row in output_rows
        ]
    if output_lineage is not None:
        known = {str(row["record_id"]) for row in captured_evidence}
        if len(output_lineage) != len(output_rows):
            raise ValueError("Invalid output lineage mapping")
        for entry, row in zip(output_lineage, output_rows, strict=True):
            record_ids = entry.get("record_ids", [entry.get("record_id")])
            if (
                entry.get("output_id") != row.get("id")
                or not isinstance(record_ids, list)
                or not record_ids
                or any(not isinstance(value, str) or value not in known for value in record_ids)
                or len(set(record_ids)) != len(record_ids)
            ):
                raise ValueError("Invalid output lineage mapping")
    grouping = (metadata or {}).get("grouping")
    groupby = grouping.get("field") if isinstance(grouping, dict) else None
    cell_lineage = build_cell_lineage(
        store,
        rid,
        output_rows,
        output_lineage,
        strings=(metadata or {}).get("string_mode") is True,
        groupby=groupby if isinstance(groupby, str) else None,
        presentation=presentation,
        schema=schema,
        protected=task.identity_fields,
    )
    item = schema["items"] if schema["type"] == "array" else schema
    requested = list(item.get("properties", {}))
    fields = ["id"] if any("id" in row for row in output_rows) else []
    fields.extend(field for field in requested if field not in fields)
    fields.extend(sorted({key for row in output_rows for key in row} - set(fields)))
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    evidence = destination.with_suffix(destination.suffix + ".evidence.json")
    events = destination.with_suffix(destination.suffix + ".events.json")
    assets = destination.with_suffix(destination.suffix + ".assets.json")
    portable = asset_bundle(store, rid)
    # A manifest certifies a complete export generation. Remove the old one before
    # writing files so an interrupted refresh cannot advertise stale checksums.
    manifest.unlink(missing_ok=True)

    def write(stream: TextIO) -> None:
        if destination.suffix.lower() == ".json":
            json.dump(output_rows, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            return
        writer = csv.writer(stream)
        writer.writerow(
            [_csv_value(key) if task.csv_mode == "spreadsheet" else key for key in fields]
        )
        for row in output_rows:
            if task.csv_mode == "json":
                cells = [
                    json.dumps(row[key], ensure_ascii=False, allow_nan=False) if key in row else ""
                    for key in fields
                ]
            else:
                cells = [_csv_value(row.get(key, "")) for key in fields]
            writer.writerow(cells)

    _atomic_write(destination, write)
    _atomic_write(evidence, lambda stream: json.dump(captured_evidence, stream, ensure_ascii=False))
    _atomic_write(
        events,
        lambda stream: json.dump(
            {"format_version": 1, "run_id": rid, "events": captured_events},
            stream,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ),
    )
    files = [destination, evidence, events]
    if portable["assets"]:
        _atomic_write(
            assets, lambda stream: json.dump(portable, stream, ensure_ascii=False, allow_nan=False)
        )
        files.append(assets)
    schema_rows = [{key: value for key, value in row.items() if key != "id"} for row in output_rows]
    valid = (
        SchemaBuilder.validator(schema).is_valid(schema_rows)
        if schema["type"] == "array"
        else all(SchemaBuilder.validator(schema).is_valid(row) for row in schema_rows)
    )
    info = {
        # Extension metadata cannot replace ledger facts, hashes or evidence claims.
        **(metadata or {}),
        "format_version": 3,
        "presentation_preferences": presentation.model_dump() if presentation else None,
        "run_id": rid,
        "goal": state["goal"],
        "model_invocations": [
            event["payload"] for event in captured_events if event["kind"] == "run_config"
        ],
        "status": state["status"],
        "reason": state["reason"],
        "records": len(output_rows),
        "schema": schema,
        "collection_schema_valid": valid,
        "task": task.model_dump(),
        "search_attempts_reserved": search_attempts,
        "search_attempt_definition": (
            "Distinct journaled reservations before transport; not confirmed billable requests"
        ),
        "model_reported_tokens": state["tokens"],
        "model_request_units": state["reserved"],
        "request_unit_definition": (
            "UTF-8 serialized model/search request content + maximum output tokens per attempt"
        ),
        "provenance": (
            "projected_dataset_values"
            if any(source.projection is not None for source in task.dataset_sources)
            else "exact_dataset_values"
            if task.dataset_sources
            else "literal_evidence_with_model_semantic_review"
        ),
        "truth_verified": False,
        "global_completeness_claimed": False,
        "csv_mode": task.csv_mode,
        "csv_fields": fields,
        "identity": task.identity_fields or "exact_record_hash",
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        **store.summary(rid),
        "asset_bundle": assets.name if portable["assets"] else None,
        "output_lineage": output_lineage,
        "output_lineage_status": "mapped" if output_lineage is not None else "unresolved",
        "cell_lineage": cell_lineage,
        "dataset_consistency": dataset_consistency,
    }
    # Publish the manifest last, after every checksummed file has been written.
    _atomic_write(manifest, lambda stream: json.dump(info, stream, ensure_ascii=False, indent=2))
    return manifest
