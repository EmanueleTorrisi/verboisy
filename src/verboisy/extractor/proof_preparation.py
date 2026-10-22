# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prepare literal proofs without changing facts, scopes or verification policy.

This is not acceptance. Prepared candidates still require deterministic validation,
semantic review and source assessment. Callers must journal changes before review.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from verboisy.core.fitness import FieldSemantics, semantics_for_pointer
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec, TemporalProof
from verboisy.evidence.snapshot import whitespace
from verboisy.evidence.verify import leaves

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_NUMBERS = {name: index for index, name in enumerate(_MONTHS, 1)}
_MONTH_NUMBERS.update({name[:3]: index for index, name in enumerate(_MONTHS, 1)})
_DATE_PATTERNS = (
    r"(?P<year>[1-9][0-9]{3})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})",
    r"(?P<month>[A-Za-z]+)\.? (?P<day>[0-9]{1,2}), (?P<year>[1-9][0-9]{3})",
    r"(?P<day>[0-9]{1,2}) (?P<month>[A-Za-z]+)\.? (?P<year>[1-9][0-9]{3})",
)


def calendar_year(value: str) -> int | None:
    """Read a complete ISO or English month-name date, never a guessed date/order.

    Other languages, slash dates, bare years, date ranges and date-times remain
    the model's responsibility. Validate the whole calendar date, including leap days.
    """
    for pattern in _DATE_PATTERNS:
        match = re.fullmatch(pattern, value)
        if match is None:
            continue
        month = match["month"]
        number = (
            int(month)
            if month.isascii() and month.isdecimal()
            else _MONTH_NUMBERS.get(month.casefold(), 0)
        )
        try:
            return date(int(match["year"]), number, int(match["day"])).year
        except ValueError:
            return None
    return None


def prepare_candidate_proofs(
    candidate: Candidate,
    page: Snapshot,
    task: TaskSpec,
    field_semantics: dict[str, FieldSemantics],
) -> tuple[Candidate, list[dict[str, Any]]]:
    """Narrow observed text quotes and complete date proofs from that same source.

    Never change the record, replace an existing temporal proof, search other
    sources, infer field semantics, apply mappings, or alter dataset projections.
    """
    if page.dataset_asset_id is not None or page.dataset_projection is not None:
        return candidate, []
    sources = {source.id: source for source in page.sources}
    if len(sources) != len(page.sources):
        return candidate, []
    prepared = candidate.model_copy(deep=True)
    changes: list[dict[str, Any]] = []
    for pointer, value in leaves(candidate.record).items():
        if not isinstance(value, str) or not whitespace(value):
            continue
        proof = prepared.evidence.get(pointer)
        if proof is None or proof.transform != "text":
            continue
        rule = task.field_rules.get(pointer)
        if rule is not None and (rule.source != "auto" or rule.mapping or rule.external):
            continue
        source = sources.get(proof.source)
        if source is None or source.kind != "text" or source.scope != candidate.scope:
            continue
        literal, quote, observed = (
            whitespace(value),
            whitespace(proof.quote),
            whitespace(source.text),
        )
        if not quote or quote not in observed:
            continue
        if literal != quote:
            # Only whole literal tokens from the original, observed quote. Do not
            # turn a partial word/number into support or find a replacement source.
            if re.search(r"(?<!\w)" + re.escape(literal) + r"(?!\w)", quote) is None:
                continue
            before = proof.model_dump(mode="json")
            proof.quote = literal
            changes.append(
                {
                    "kind": "narrow_text_quote",
                    "pointer": pointer,
                    "before": before,
                    "after": proof.model_dump(mode="json"),
                }
            )
        if pointer in prepared.temporal_evidence:
            continue
        semantics = semantics_for_pointer(field_semantics, pointer)
        if (
            semantics is None
            or semantics.temporal_class != "event"
            or (semantics.reference_period not in {"required", "preferred"})
        ):
            continue
        year = calendar_year(literal)
        if year is None:
            continue
        temporal = TemporalProof(source=proof.source, quote=literal, reference_year=year)
        prepared.temporal_evidence[pointer] = temporal
        changes.append(
            {
                "kind": "event_date_reference_year",
                "pointer": pointer,
                "before": None,
                "after": temporal.model_dump(mode="json"),
            }
        )
    return (prepared if changes else candidate), changes
