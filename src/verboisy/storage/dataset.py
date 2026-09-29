"""Atomic exports; the manifest written last commits a checksummed generation."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, TextIO

from verboisy.evidence.models import TaskSpec
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.storage.exporters import _atomic_write, _csv_value
from verboisy.storage.research import ResearchStore


def export_dataset(
    store: ResearchStore, rid: str, destination: Path, schema: dict[str, Any], task: TaskSpec
) -> Path:
    rows = store.records(rid)
    item = schema["items"] if schema["type"] == "array" else schema
    fields = list(item.get("properties", {}))
    fields.extend(sorted({k for r in rows for k in r} - set(fields)))
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    evidence = destination.with_suffix(destination.suffix + ".evidence.json")
    manifest.unlink(missing_ok=True)

    def write(stream: TextIO) -> None:
        if destination.suffix.lower() == ".json":
            json.dump(rows, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        else:
            writer = csv.writer(stream)
            writer.writerow(
                [_csv_value(k) if task.csv_mode == "spreadsheet" else k for k in fields]
            )
            for row in rows:
                if task.csv_mode == "json":
                    cells = [
                        json.dumps(row[k], ensure_ascii=False, allow_nan=False) if k in row else ""
                        for k in fields
                    ]
                else:
                    cells = [_csv_value(row.get(k, "")) for k in fields]
                writer.writerow(cells)

    _atomic_write(destination, write)
    _atomic_write(evidence, lambda f: json.dump(store.evidence(rid), f, ensure_ascii=False))
    state = store.load(rid)
    valid = (
        SchemaBuilder.validator(schema).is_valid(rows)
        if schema["type"] == "array"
        else all(SchemaBuilder.validator(schema).is_valid(r) for r in rows)
    )
    info = {
        "format_version": 1,
        "run_id": rid,
        "goal": state["goal"],
        "model_invocations": [
            json.loads(row[0])
            for row in store.db.execute(
                "SELECT payload FROM events WHERE run_id=? AND kind='run_config' ORDER BY id",
                (rid,),
            )
        ],
        "status": state["status"],
        "reason": state["reason"],
        "records": len(rows),
        "schema": schema,
        "collection_schema_valid": valid,
        "task": task.model_dump(),
        "model_reported_tokens": state["tokens"],
        "model_request_units": state["reserved"],
        "request_unit_definition": "UTF-8 message bytes + maximum output tokens per attempt",
        "provenance": "literal_evidence_with_model_semantic_review",
        "truth_verified": False,
        "global_completeness_claimed": False,
        "csv_mode": task.csv_mode,
        "csv_fields": fields,
        "identity": task.identity_fields or "exact_record_hash",
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (destination, evidence)
        },
        **store.summary(rid),
    }
    _atomic_write(manifest, lambda f: json.dump(info, f, ensure_ascii=False, indent=2))
    return manifest
