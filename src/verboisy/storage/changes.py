# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Durable user decisions about proposed research requirements.

This boundary changes requirements, never evidence or request accounting.
Automatic feasibility detection can submit proposals through this same boundary.
"""

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import Field, ValidationError

from verboisy.core.planner import build_research_plan
from verboisy.evidence.models import StrictModel, TaskSpec
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.research_contract import validate_research_contract
from verboisy.storage.event_journal import decode_event_rows
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError


class ChangeEvidence(StrictModel):
    pointer: str
    snapshot_id: str
    scope: str
    source: str
    quote: str


class ChangeRequest(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    goal: str = Field(min_length=1, max_length=10000)
    schema_: dict[str, Any] = Field(alias="schema")
    task: TaskSpec
    evidence: list[ChangeEvidence] = Field(default_factory=list, max_length=20)


class SavedChange(StrictModel):
    version: Literal[1] = 1
    proposal_id: str = Field(min_length=1)
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: ChangeRequest


def _baseline(state: dict[str, Any]) -> str:
    payload = [state["goal"], json.loads(state["schema_json"]), json.loads(state["task_json"])]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class PreviousRequirements(StrictModel):
    goal: str
    schema_: dict[str, Any] = Field(alias="schema")
    task: TaskSpec


class SavedDecision(StrictModel):
    proposal_id: str = Field(min_length=1)
    decision: Literal["accepted", "declined"]
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_requirements: PreviousRequirements


def _validated_change_history(
    events: list[dict[str, Any]], state: dict[str, Any]
) -> SavedChange | None:
    """Replay exact proposal/decision pairs without changing historical payloads.

    A terminal event cannot close an unrelated proposal or silently clear caches.
    Validate the complete decision history before returning the pending contract;
    otherwise a damaged older decision could still affect later planning replay.
    """
    pending: SavedChange | None = None
    expected: ChangeRequest | PreviousRequirements | None = None
    proposal_ids: set[str] = set()
    for event in events:
        if event["kind"] == "change_proposed":
            try:
                proposed = SavedChange.model_validate(event["payload"])
            except ValidationError:
                raise VerboisyError("Invalid saved change proposal") from None
            if not proposed.request.description.strip() or not proposed.request.goal.strip():
                raise VerboisyError("Invalid saved change proposal")
            if pending is not None or proposed.proposal_id in proposal_ids:
                raise VerboisyError("Saved change history failed integrity verification")
            proposal_ids.add(proposed.proposal_id)
            pending = proposed
        elif event["kind"] == "change_decided":
            try:
                decision = SavedDecision.model_validate(event["payload"])
            except ValidationError:
                raise VerboisyError("Invalid saved change decision") from None
            if (
                pending is None
                or decision.proposal_id != pending.proposal_id
                or decision.baseline_sha256 != pending.baseline_sha256
            ):
                raise VerboisyError("Saved change history failed integrity verification")
            # Hash the original saved JSON, rather than a model dump which could
            # insert optional defaults into older task requirements.
            previous = event["payload"]["previous_requirements"]
            baseline = _baseline(
                {
                    "goal": previous["goal"],
                    "schema_json": json.dumps(previous["schema"]),
                    "task_json": json.dumps(previous["task"]),
                }
            )
            if baseline != decision.baseline_sha256:
                raise VerboisyError("Saved change history failed integrity verification")
            expected = (
                pending.request
                if decision.decision == "accepted"
                else decision.previous_requirements
            )
            pending = None
    if pending is None and expected is not None:
        try:
            current_task = TaskSpec.model_validate_json(state["task_json"])
            current = {**state, "task_json": current_task.model_dump_json(exclude={"seed_urls"})}
            decided = {
                "goal": expected.goal,
                "schema_json": json.dumps(expected.schema_),
                "task_json": expected.task.model_dump_json(exclude={"seed_urls"}),
            }
            # Discovery publishes seeds separately from user requirement decisions.
            # Normalize task defaults so older valid task JSON remains comparable.
            if _baseline(current) != _baseline(decided):
                raise ValueError("Current requirements differ from the decided contract")
        except (ValueError, TypeError):
            raise VerboisyError("Saved requirements differ from the last decision") from None
    return pending


def pending_change(store: ResearchStore, rid: str) -> SavedChange | None:
    """Read unresolved requirements only after validating their decision history."""
    state = store.load(rid)
    rows = store.db.execute(
        "SELECT kind,payload,created_at FROM events WHERE run_id=? "
        "AND kind IN ('change_proposed','change_decided') ORDER BY id",
        (rid,),
    ).fetchall()
    return _validated_change_history(decode_event_rows(rows), state)


def _eligible(store: ResearchStore, rid: str) -> dict[str, Any]:
    state = store.load(rid)
    if state["status"] == "COMPLETED":
        raise VerboisyError("Completed runs cannot change requirements")
    if store.db.execute("SELECT 1 FROM records WHERE run_id=? LIMIT 1", (rid,)).fetchone():
        raise VerboisyError("Requirement changes currently require a run with no accepted rows")
    if TaskSpec.model_validate_json(state["task_json"]).dataset_sources:
        raise VerboisyError("Dataset requirement changes need a separate reingestion workflow")
    return state


def propose_change(store: ResearchStore, rid: str, value: Any) -> SavedChange:
    """Validate, save and pause for an exact proposed replacement contract."""
    if pending_change(store, rid) is not None:
        raise VerboisyError("Resolve the pending proposal before offering another")
    state = _eligible(store, rid)
    try:
        request = ChangeRequest.model_validate(value)
        normalized = SchemaBuilder.normalize(request.schema_)
        validate_research_contract(normalized, request.task)
    except (ValidationError, VerboisyError):
        raise VerboisyError("Invalid proposed requirements") from None
    if not request.description.strip() or not request.goal.strip():
        raise VerboisyError("Proposal description and goal must not be blank")
    if request.task.dataset_sources:
        raise VerboisyError("This change workflow currently supports browser research only")
    request = request.model_copy(update={"schema_": normalized})
    proposed = {
        "goal": request.goal,
        "schema_json": json.dumps(request.schema_),
        "task_json": request.task.model_dump_json(),
    }
    if _baseline(proposed) == _baseline(state):
        raise VerboisyError("Proposal must change the saved requirements")
    change = SavedChange(
        proposal_id=str(uuid.uuid4()), baseline_sha256=_baseline(state), request=request
    )
    with store.db:
        store.db.execute(
            "INSERT INTO events(run_id,kind,payload) VALUES (?,'change_proposed',?)",
            (rid, change.model_dump_json(by_alias=True)),
        )
        store.db.execute(
            "UPDATE research_runs SET status='PAUSED',reason='proposed_changes' WHERE id=?",
            (rid,),
        )
    return change


def decide_change(store: ResearchStore, rid: str, *, accept: bool) -> SavedChange | None:
    """Commit requirements and decision together, or continue the original contract."""
    change = pending_change(store, rid)
    if change is None:
        if accept:
            raise VerboisyError("No pending proposal; use --resume to continue this run")
        return None
    state = _eligible(store, rid)
    if _baseline(state) != change.baseline_sha256:
        raise VerboisyError("Saved requirements changed; the proposal is stale")
    # Revalidate persisted schema before any mutation, even if the ledger was edited.
    normalized = SchemaBuilder.normalize(change.request.schema_)
    validate_research_contract(normalized, change.request.task)
    if change.request.task.dataset_sources:
        raise VerboisyError("This change workflow currently supports browser research only")
    # The decision and its requirement update share a transaction. Old evidence and
    # consumed budgets remain available even after the browser frontier is revisited.
    with store.db:
        if accept:
            store.db.execute(
                "UPDATE research_runs SET goal=?,schema_json=?,task_json=? WHERE id=?",
                (
                    change.request.goal,
                    json.dumps(change.request.schema_, ensure_ascii=False, allow_nan=False),
                    change.request.task.model_dump_json(),
                    rid,
                ),
            )
            store.db.execute(
                "UPDATE pages SET status='queued',reason=NULL WHERE run_id=?",
                (rid,),
            )
            for url in change.request.task.seed_urls:
                store.db.execute(
                    "INSERT OR IGNORE INTO pages(run_id,url,depth) VALUES (?,?,0)", (rid, url)
                )
            store.db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES (?,'research_plan',?)",
                (
                    rid,
                    json.dumps(
                        build_research_plan(
                            change.request.schema_, change.request.task.target_records
                        ).as_event()
                    ),
                ),
            )
        store.db.execute(
            "INSERT INTO events(run_id,kind,payload) VALUES (?,'change_decided',?)",
            (
                rid,
                json.dumps(
                    {
                        "proposal_id": change.proposal_id,
                        "decision": "accepted" if accept else "declined",
                        "baseline_sha256": change.baseline_sha256,
                        "previous_requirements": {
                            "goal": state["goal"],
                            "schema": json.loads(state["schema_json"]),
                            "task": json.loads(state["task_json"]),
                        },
                    }
                ),
            ),
        )
        store.db.execute("UPDATE research_runs SET status='PAUSED',reason=NULL WHERE id=?", (rid,))
    return change


def current_requirement_events(store: ResearchStore, rid: str, kind: str) -> list[dict[str, Any]]:
    """Use planning caches made after the most recent accepted requirement change."""
    events = store.events(rid)
    # Cache-only readers need no run state until a decision establishes a
    # contract to compare. History validation still runs for every reader.
    state = store.load(rid) if any(event["kind"] == "change_decided" for event in events) else {}
    _validated_change_history(events, state)
    result: list[dict[str, Any]] = []
    for event in events:
        if event["kind"] == "change_decided" and event["payload"]["decision"] == "accepted":
            result.clear()
        elif event["kind"] == kind:
            result.append(event)
    return result
