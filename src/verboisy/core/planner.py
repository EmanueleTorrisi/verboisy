# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cheap deterministic planning for efficient autonomous research."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import unquote

TaskShape = Literal[
    "single_record",
    "bounded_list",
    "open_list",
]

TemporalMode = Literal[
    "latest",
    "year",
    "range",
    "series",
]


@dataclass(frozen=True)
class TemporalIntent:
    """Deterministic interpretation of the user's requested time horizon."""

    mode: TemporalMode
    start_year: int | None = None
    end_year: int | None = None

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def infer_temporal_intent(
    goal: str,
    *,
    current_year: int,
) -> TemporalIntent:
    """Infer explicit historical intent; otherwise require latest data."""

    normalized = unquote(goal).casefold()

    range_match = re.search(
        r"\b(?:from|between)?\s*((?:18|19|20)\d{2})"
        r"\s*(?:-|\u2013|\u2014|to|through|and)\s*"
        r"((?:18|19|20)\d{2})\b",
        normalized,
    )

    if range_match:
        first = int(range_match.group(1))
        second = int(range_match.group(2))

        return TemporalIntent(
            mode="range",
            start_year=min(first, second),
            end_year=max(first, second),
        )

    decade_match = re.search(
        r"\b((?:18|19|20)\d)0s\b",
        normalized,
    )

    if decade_match:
        start = int(decade_match.group(1)) * 10

        return TemporalIntent(
            mode="range",
            start_year=start,
            end_year=start + 9,
        )

    short_decade_match = re.search(
        r"(?<!\d)(\d{2})s\b",
        normalized,
    )

    if short_decade_match:
        decade = int(short_decade_match.group(1))
        current_two_digits = current_year % 100

        century = current_year // 100 if decade <= current_two_digits else current_year // 100 - 1

        start = century * 100 + decade

        return TemporalIntent(
            mode="range",
            start_year=start,
            end_year=start + 9,
        )

    years = [
        int(value)
        for value in re.findall(
            r"\b(?:18|19|20)\d{2}\b",
            normalized,
        )
    ]

    if len(years) >= 2:
        return TemporalIntent(
            mode="range",
            start_year=min(years),
            end_year=max(years),
        )

    if len(years) == 1:
        return TemporalIntent(
            mode="year",
            start_year=years[0],
            end_year=years[0],
        )

    series_signals = (
        "over time",
        "through the years",
        "by year",
        "year by year",
        "yearly",
        "historical trend",
        "historical data",
        "time series",
    )

    if any(signal in normalized for signal in series_signals):
        return TemporalIntent(mode="series")

    return TemporalIntent(mode="latest")


_GENERIC_FIELD_PARTS = {
    "amount",
    "count",
    "field",
    "number",
    "text",
    "value",
}

_STRUCTURED_HINTS = (
    "table",
    "list",
    "dataset",
    "database",
    "statistics",
    "stats",
    "directory",
    "catalog",
)

_LOW_VALUE_HINTS = (
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "pinterest.com",
    "scribd.com",
    "x.com/",
)


@dataclass(frozen=True)
class ResearchPlan:
    """A cheap plan used before expensive browser/model work."""

    task_shape: TaskShape
    target_records: int | None
    field_terms: tuple[str, ...]
    initial_source_goal: int
    probe_batches: int
    rejection_cutoff: int

    def source_score(
        self,
        title: str,
        url: str,
    ) -> int:
        """Estimate source usefulness from discovery metadata."""

        title_text = unquote(title).casefold()
        url_text = unquote(url).casefold()
        combined = f"{title_text} {url_text}"

        score = 0

        for term in self.field_terms:
            if term in title_text:
                score += 4
            if term in url_text:
                score += 2

        for hint in _STRUCTURED_HINTS:
            if hint in combined:
                score += 2

        for hint in _LOW_VALUE_HINTS:
            if hint in combined:
                score -= 8

        return score

    def split_initial_sources(
        self,
        urls: list[str],
    ) -> tuple[list[str], list[str]]:
        """Activate only the best initial sources for bounded datasets."""

        if self.task_shape != "bounded_list":
            return list(urls), []

        cutoff = min(
            self.initial_source_goal,
            len(urls),
        )

        return (
            list(urls[:cutoff]),
            list(urls[cutoff:]),
        )

    def evidence_score(
        self,
        text: str,
        *,
        source_count: int = 0,
    ) -> int:
        """Score observed evidence cheaply before spending an LLM call."""

        normalized = unquote(text).casefold()

        field_coverage = sum(term in normalized for term in self.field_terms)
        structured_signals = sum(hint in normalized for hint in _STRUCTURED_HINTS)

        return field_coverage * 100 + structured_signals * 10 + min(source_count, 50)

    def should_stop_unproductive_page(
        self,
        *,
        batches_seen: int,
        accepted: int,
        rejected: int,
    ) -> bool:
        """Stop spending on a page only after enough negative evidence."""

        return (
            batches_seen >= self.probe_batches
            and accepted == 0
            and rejected >= self.rejection_cutoff
        )

    def as_event(self) -> dict[str, Any]:
        return asdict(self)


def _field_terms(
    schema: dict[str, Any],
) -> tuple[str, ...]:
    item = (
        schema["items"]
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict)
        else schema
    )

    properties = item.get("properties", {})

    terms: set[str] = set()

    for field in properties:
        spaced = re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1 \2",
            field,
        )

        for part in re.findall(
            r"[a-z0-9]+",
            spaced.casefold(),
        ):
            if len(part) >= 3 and part not in _GENERIC_FIELD_PARTS:
                terms.add(part)

    return tuple(sorted(terms))


def source_productivity_score(
    accepted: int,
    misses: int,
) -> float:
    """Return smoothed marginal dataset yield around a neutral zero."""

    return (accepted + 1) / (accepted + misses + 2) - 0.5


def build_research_plan(
    schema: dict[str, Any],
    target_records: int | None,
) -> ResearchPlan:
    """Build an effort plan from dataset shape and requested size."""

    is_array = schema.get("type") == "array"

    if not is_array:
        shape: TaskShape = "single_record"
        initial_sources = 3
        probe_batches = 2
        rejection_cutoff = 4

    elif target_records is None:
        shape = "open_list"
        initial_sources = 8
        probe_batches = 4
        rejection_cutoff = 20

    elif target_records <= 10:
        shape = "bounded_list"
        initial_sources = 3
        probe_batches = 2
        rejection_cutoff = max(
            4,
            target_records,
        )

    elif target_records <= 50:
        shape = "bounded_list"
        initial_sources = 5
        probe_batches = 3
        rejection_cutoff = 12

    else:
        shape = "bounded_list"
        initial_sources = 8
        probe_batches = 4
        rejection_cutoff = 20

    return ResearchPlan(
        task_shape=shape,
        target_records=target_records,
        field_terms=_field_terms(schema),
        initial_source_goal=initial_sources,
        probe_batches=probe_batches,
        rejection_cutoff=rejection_cutoff,
    )
