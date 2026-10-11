# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Ground model-suggested alternatives before offering an exact replacement contract."""

import copy
import json

from verboisy.evidence.models import ResearchSuggestion, Snapshot, TaskSpec
from verboisy.evidence.snapshot import whitespace
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.storage.changes import SavedChange, pending_change, propose_change
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


def _pointer(name: str) -> str:
    return "/" + name.replace("~", "~0").replace("/", "~1")


def offer_research_change(
    store: ResearchStore, rid: str, page: Snapshot, suggestions: list[ResearchSuggestion]
) -> SavedChange | None:
    """Offer only with no accepted rows, checked quotes, and unchanged task policy.

    The caller must first check the batch and suppress offers if any candidate qualifies.
    Suggestions are untrusted alternatives, not factual conclusions about global coverage.
    """
    if not suggestions:
        return None
    state = store.load(rid)
    task = TaskSpec.model_validate_json(state["task_json"])
    if (
        state["status"] == "COMPLETED"
        or task.dataset_sources
        or store.records(rid)
        or pending_change(store, rid) is not None
    ):
        return None
    schema = json.loads(state["schema_json"])
    original = schema["items"] if schema["type"] == "array" else schema
    properties = original.get("properties", {})
    sources = {source.id: source for source in page.sources}
    events = store.events(rid)
    declined = {
        e["payload"]["proposal_id"]
        for e in events
        if e["kind"] == "change_decided" and e["payload"]["decision"] == "declined"
    }
    for suggestion in suggestions:
        goal = suggestion.goal if suggestion.goal is not None else state["goal"]
        changed = {
            name for name, field in suggestion.columns.items() if properties.get(name) != field
        }
        dropped = set(suggestion.drop_columns)
        affected = {_pointer(name) for name in changed | dropped}
        if (
            not goal.strip()
            or not (affected or goal != state["goal"])
            or not dropped <= properties.keys()
            or dropped & suggestion.columns.keys()
            or any(
                pointer == policy
                or policy.startswith(pointer + "/")
                or pointer.startswith(policy + "/")
                for pointer in affected
                for policy in set(task.identity_fields)
                | set(task.field_rules)
                | (
                    {
                        _pointer(name)
                        for name in [
                            task.time_series.timestamp_field,
                            *task.time_series.series_fields,
                        ]
                    }
                    if task.time_series is not None
                    else set()
                )
            )
            or any(not name.strip() or len(name) > 100 for name in changed | dropped)
        ):
            continue
        required_evidence = affected | ({"/"} if goal != state["goal"] else set())
        evidence = []
        for proof in suggestion.evidence:
            source = sources.get(proof.source)
            quote = whitespace(proof.quote)
            if (
                proof.pointer in required_evidence
                and source is not None
                and source.kind == "text"
                and source.scope == proof.scope
                and quote
                and quote in whitespace(source.text)
            ):
                evidence.append({**proof.model_dump(), "snapshot_id": page.id})
        # Every affected field needs its own checked citation. A valid quote for one
        # column must not authorise unrelated additions, removals or goal changes.
        if {proof["pointer"] for proof in evidence} != required_evidence:
            continue
        proposed = copy.deepcopy(schema)
        target = proposed["items"] if proposed["type"] == "array" else proposed
        target.setdefault("properties", {}).update(suggestion.columns)
        for name in dropped:
            del target["properties"][name]
        target["required"] = [name for name in target.get("required", []) if name not in dropped]
        # New columns are required keys, with nullable types available for unknown values.
        target["required"] = sorted(set(target["required"]) | (changed - properties.keys()))
        try:
            proposed = SchemaBuilder.normalize(proposed)
        except VerboisyError:
            continue
        request_task = task.model_dump()
        if any(
            e["kind"] == "change_proposed"
            and e["payload"]["proposal_id"] in declined
            and e["payload"]["request"]["goal"] == goal
            and e["payload"]["request"]["schema"] == proposed
            and TaskSpec.model_validate(e["payload"]["request"]["task"]) == task
            for e in events
        ):
            continue
        added = sorted(changed - properties.keys())
        modified = sorted(changed & properties.keys())
        description = (
            "Alternative suggested from the cited evidence checked so far. "
            f"Proposed goal: {goal}. Added columns: {added}; dropped columns: {sorted(dropped)}; "
            f"changed columns: {modified}. Inspect the saved schema for exact types and meanings. "
            "This is not a claim that the original requirements are impossible everywhere. "
            "Source restrictions, request budgets and task policy remain unchanged."
        )
        return propose_change(
            store,
            rid,
            {
                "description": description,
                "goal": goal,
                "schema": proposed,
                "task": request_task,
                "evidence": evidence,
            },
        )
    return None
