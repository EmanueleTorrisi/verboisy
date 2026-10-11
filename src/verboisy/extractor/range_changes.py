# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Offer range-compatible schemas from observed evidence, without new model calls."""

import copy
import json
import re
from decimal import Decimal

from verboisy.evidence.models import PageProposal, RangeConflict, Snapshot, TaskSpec
from verboisy.evidence.snapshot import whitespace
from verboisy.storage.changes import SavedChange, pending_change, propose_change
from verboisy.storage.json_payload import decode_saved_json
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT = r"[A-Za-z°µμ%][A-Za-z0-9°µμ%/²³]*"
_INTERVAL = re.compile(
    rf"(?<![\w.,+\-\u2013\u2014])(?P<low>{_NUMBER})\s*(?P<left_unit>{_UNIT})?"
    rf"\s*(?:[-\u2013\u2014]|\bto\b)\s*(?P<high>{_NUMBER})"
    rf"(?:\s*(?P<right_unit>{_UNIT}))?(?!\w|[.,]\d|[\-\u2013\u2014])"
)


class ProposedChangesPauseError(Exception):
    """Stop the current crawl after saving an actionable proposal."""


def interval_quote(value: str) -> str | None:
    """Recognize a complete, ascending interval; never synthesize an endpoint."""
    match = _INTERVAL.fullmatch(whitespace(value))
    if match is None:
        return None
    low, high = (Decimal(match[k].replace(",", "")) for k in ("low", "high"))
    if low >= high:
        return None
    left, right = match["left_unit"], match["right_unit"]
    if any(unit and re.fullmatch(r"[eE]\d+", unit) for unit in (left, right)):
        return None
    if left and right and left != right:
        return None
    return value


def candidate_range_conflicts(proposal: PageProposal) -> list[RangeConflict]:
    """Also recognize old numeric proofs that quoted an interval in context."""
    result = list(proposal.range_conflicts)
    for candidate in proposal.candidates:
        for pointer, proof in candidate.evidence.items():
            if proof.transform not in {"number", "integer"}:
                continue
            for match in _INTERVAL.finditer(proof.quote):
                quote = match.group(0)
                if interval_quote(quote) is not None:
                    result.append(
                        RangeConflict(
                            pointer=pointer, scope=candidate.scope, source=proof.source, quote=quote
                        )
                    )
    return result


def offer_range_change(
    store: ResearchStore,
    rid: str,
    page: Snapshot,
    conflicts: list[RangeConflict],
) -> SavedChange | None:
    """Pause only for eligible numeric columns and replayable observed intervals."""
    if not conflicts:
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
    record_schema = schema.get("items", {}) if schema.get("type") == "array" else schema
    properties = record_schema.get("properties", {})
    sources = {source.id: source for source in page.sources}
    evidence: dict[str, dict[str, str]] = {}
    for conflict in conflicts:
        if len(conflict.pointer) > 200:
            continue
        name = conflict.pointer[1:].replace("~1", "/").replace("~0", "~")
        if conflict.pointer != "/" + name.replace("~", "~0").replace("/", "~1"):
            continue
        field = properties.get(name)
        if not isinstance(field, dict):
            continue
        types = field.get("type")
        types = types if isinstance(types, list) else [types]
        rule = task.field_rules.get(conflict.pointer)
        if (
            not set(types) <= {"number", "integer", "null"}
            or not set(types) & {"number", "integer"}
            or conflict.pointer in task.identity_fields
            or task.time_series is not None
            and name in {task.time_series.timestamp_field, *task.time_series.series_fields}
            or any(
                key not in {"type", "title", "description"} and not key.startswith("x-")
                for key in field
            )
            or rule is not None
            and (rule.mapping or rule.source != "auto" or rule.external)
        ):
            continue
        source = sources.get(conflict.source)
        if (
            source is None
            or source.scope != conflict.scope
            or source.kind != "text"
            or interval_quote(conflict.quote) is None
        ):
            continue
        quote = whitespace(conflict.quote)
        if not re.search(
            r"(?<![\w.,+\-\u2013\u2014])" + re.escape(quote) + r"(?!\w|[.,]\d|[\-\u2013\u2014])",
            whitespace(source.text),
        ):
            continue
        evidence.setdefault(
            conflict.pointer,
            {
                "pointer": conflict.pointer,
                "snapshot_id": page.id,
                "scope": conflict.scope,
                "source": conflict.source,
                "quote": conflict.quote,
            },
        )
    if not evidence:
        return None
    # Keep a bounded offer readable; remaining columns can be assessed separately.
    evidence = dict(sorted(evidence.items())[:10])
    proposed = copy.deepcopy(schema)
    target = proposed["items"] if proposed.get("type") == "array" else proposed
    for pointer in evidence:
        name = pointer[1:].replace("~1", "/").replace("~0", "~")
        field = target["properties"][name]
        types = field["type"]
        field["type"] = (
            ["string", "null"] if isinstance(types, list) and "null" in types else "string"
        )
    # A decline applies to this exact replacement contract, regardless of repeat evidence.
    # Compare the replacement contract, not its wording or citation order, so new
    # evidence cannot repeatedly prompt a user who declined the same schema change.
    events = store.events(rid)
    declined = {
        event["payload"]["proposal_id"]
        for event in events
        if event["kind"] == "change_decided" and event["payload"]["decision"] == "declined"
    }
    for event in events:
        if event["kind"] != "change_proposed" or event["payload"]["proposal_id"] not in declined:
            continue
        previous = event["payload"]["request"]
        if (
            previous["schema"] == proposed
            and previous["goal"] == state["goal"]
            and TaskSpec.model_validate(previous["task"]) == task
        ):
            return None
    columns = ", ".join(evidence)
    description = (
        f"The cited sources contain intervals for numeric columns {columns}. "
        "Accepting changes those columns to strings containing the exact source-reported "
        "range, including its printed unit. Other requirements remain unchanged. "
        "For numeric output, use --resume to keep the schema or start a new run with "
        "separate min/max columns. This does not establish that all sources report ranges."
    )
    return propose_change(
        store,
        rid,
        {
            "description": description,
            "goal": state["goal"],
            "schema": proposed,
            "task": task.model_dump(),
            "evidence": list(evidence.values()),
        },
    )


def _copy_snapshot(page: Snapshot) -> Snapshot:
    """Retain independent mutable fields without recursively copying scalar sources."""
    # Source fields are immutable JSON scalars. Copy each model and the list;
    # only the optional projection contains further nested mutable models.
    projection = page.dataset_projection
    return page.model_copy(
        update={
            "sources": [source.model_copy() for source in page.sources],
            "dataset_projection": projection.model_copy(deep=True)
            if projection is not None
            else None,
        }
    )


def saved_range_evidence(store: ResearchStore, rid: str) -> list[tuple[Snapshot, PageProposal]]:
    """Validate the bounded saved scan before any offer can be published.

    Missing snapshots remain unavailable evidence and are skipped. Owned saved
    snapshots and rejected candidates must decode without ambiguity, including
    candidates which do not contain intervals. Keep newest-first ordering and
    the existing limit; this scan never fetches or repairs historical evidence.
    """
    rows = store.db.execute(
        "SELECT payload,snapshot_id FROM candidates WHERE run_id=? AND accepted=0 "
        "ORDER BY id DESC LIMIT 100",
        (rid,),
    ).fetchall()
    result = []
    snapshots: dict[str | None, Snapshot | None] = {}
    for row in rows:
        snapshot_id = row["snapshot_id"]
        if snapshot_id not in snapshots:
            snapshots[snapshot_id] = store.load_snapshot(rid, snapshot_id)
        page = snapshots[snapshot_id]
        if page is None:
            continue
        try:
            proposal = PageProposal.model_validate(
                {"candidates": [decode_saved_json(row["payload"])]}
            )
        except (ValueError, TypeError) as error:
            raise VerboisyError(
                "Stored rejected candidate failed integrity verification"
            ) from error
        # The cache lives only for this scan. Returned entries retain independent
        # mutable models, so one consumer cannot change another candidate's page.
        result.append((_copy_snapshot(page), proposal))
    return result


def offer_saved_range_change(
    store: ResearchStore,
    rid: str,
    *,
    saved_evidence: list[tuple[Snapshot, PageProposal]] | None = None,
) -> SavedChange | None:
    """Offer from a validated scan without spending another provider request."""
    evidence = saved_range_evidence(store, rid) if saved_evidence is None else saved_evidence
    for page, proposal in evidence:
        change = offer_range_change(store, rid, page, candidate_range_conflicts(proposal))
        if change is not None:
            return change
    return None
