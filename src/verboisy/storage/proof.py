# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Human-readable proof reports reconstructed from persisted run facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verboisy.storage.exporters import _atomic_write
from verboisy.storage.path_safety import protected_run_paths, validate_output_paths
from verboisy.storage.research import ResearchStore


def export_proof(
    store: ResearchStore,
    rid: str,
    destination: Path,
    *,
    notices: list[str] | None = None,
    smartid_decisions: list[dict[str, Any]] | None = None,
    public_ids: dict[str, int] | None = None,
    output_lineage: list[dict[str, Any]] | None = None,
) -> Path:
    """Render persisted source, evidence, transformation, and relationship decisions."""

    state = store.load(rid)
    evidence = store.evidence(rid)
    events = store.events(rid)
    proof_path = destination.with_name(destination.stem + ".proof.txt")
    validate_output_paths(
        (proof_path,), protected_run_paths(store.path, state["task_json"], events)
    )

    def write(stream: Any) -> None:
        stream.write("Verboisy proof report\n")
        stream.write("=====================\n\n")
        stream.write(f"Run ID: {rid}\n")
        stream.write(f"Status: {state['status']}\n")
        stream.write(f"Goal: {state['goal']}\n\n")
        stream.write("Pages visited or queued\n")
        stream.write("-----------------------\n")
        for page in store.pages(rid):
            stream.write(
                f"{page['status']}: {page['url']}"
                + (f" ({page['reason']})" if page.get("reason") else "")
                + "\n"
            )
        if output_lineage is not None:
            stream.write("\nExported rows and evidence contributors\n")
            stream.write("--------------------------------------\n")
            for mapping in output_lineage:
                stream.write(f"\nOutput record {mapping['output_id']}\n")
                contributors = mapping.get("record_ids", [mapping.get("record_id")])
                for contributor in contributors:
                    stream.write(f"Contributor evidence: {contributor}\n")
        stream.write("\nSources and accepted evidence\n")
        stream.write("-----------------------------\n")
        if not evidence:
            stream.write("No accepted records were persisted.\n")
        for entry in evidence:
            snapshot = entry["snapshot"]
            candidate = entry["candidate"]
            internal_id = str(entry.get("record_id") or "")

            record_id = (public_ids or {}).get(
                internal_id,
                entry["row_index"] + 1,
            )

            if output_lineage is not None:
                stream.write(f"\nEvidence record {internal_id}\n")
            else:
                stream.write(f"\nRecord {record_id}\n")
            stream.write(f"Source: {snapshot['url']}\n")
            stream.write(f"Fetched: {snapshot['fetched_at']}\n")
            stream.write("Fields:\n")
            for pointer, proof in candidate.get("evidence", {}).items():
                quote = proof.get("quote", "")
                stream.write(
                    f"  {pointer}: source={proof.get('source')} transform={proof.get('transform')}"
                )
                if quote:
                    stream.write(f" quote={json.dumps(quote, ensure_ascii=False)}")
                stream.write("\n")
        stream.write("\nRun decisions\n")
        stream.write("-------------\n")
        for event in events:
            if event["kind"] == "run_config":
                continue
            stream.write(
                f"{event['created_at']} {event['kind']}: "
                f"{json.dumps(event['payload'], ensure_ascii=False, sort_keys=True)}\n"
            )
        for notice in notices or []:
            stream.write(f"transform: {notice}\n")
        for decision in smartid_decisions or []:
            stream.write(
                "smartid: " + json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n"
            )

    _atomic_write(proof_path, write)
    return proof_path
