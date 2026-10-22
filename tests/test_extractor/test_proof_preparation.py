# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Proof preparation must preserve facts and reject invented or ambiguous support."""

from copy import deepcopy

import pytest
from verboisy.core.fitness import FieldSemantics, build_field_semantics, temporal_errors
from verboisy.core.planner import TemporalIntent
from verboisy.evidence.models import (
    Candidate,
    FieldRule,
    ProjectionPlan,
    Snapshot,
    Source,
    TaskSpec,
)
from verboisy.evidence.verify import verify
from verboisy.extractor.proof_preparation import calendar_year, prepare_candidate_proofs

SCHEMA = {
    "type": "object",
    "properties": {"version": {"type": "string"}, "release_date": {"type": "string"}},
    "required": ["version", "release_date"],
    "additionalProperties": False,
}
SEMANTICS = {
    "/release_date": FieldSemantics(
        pointer="/release_date", temporal_class="event", reference_period="required"
    ),
}


def example():
    page = Snapshot(
        id="capture",
        url="https://example.test/release/",
        fetched_at="2026-10-22",
        content_hash="fixture",
        truncated=False,
        sources=[
            Source(id="title", kind="text", scope="release", text="Runtime 9.1.0"),
            Source(id="date", kind="text", scope="release", text="Oct. 7, 2024"),
        ],
    )
    candidate = Candidate(
        scope="release",
        record={"version": "9.1.0", "release_date": "Oct. 7, 2024"},
        evidence={
            "/version": {"source": "title", "quote": "Runtime 9.1.0", "transform": "text"},
            "/release_date": {"source": "date", "quote": "Oct. 7, 2024", "transform": "text"},
        },
    )
    return candidate, page


@pytest.mark.parametrize(
    "value,year",
    [
        ("2024-02-29", 2024),
        ("2000-02-29", 2000),
        ("9999-12-31", 9999),
        ("Oct. 7, 2024", 2024),
        ("October 7, 2024", 2024),
        ("OCT 7, 2024", 2024),
        ("7 October 2024", 2024),
        ("7 Oct. 2024", 2024),
        ("May 1, 1000", 1000),
        ("2023-02-29", None),
        ("1900-02-29", None),
        ("2024-13-01", None),
        ("April 31, 2024", None),
        ("Feb. 29, 2023", None),
        ("7 Unknown 2024", None),
        ("07/10/2024", None),
        ("2024", None),
        ("2024-2025", None),
        ("Oct. 7, 2024 to Oct. 9, 2024", None),
        ("2024-10-07T12:00:00Z", None),
        ("7 ottobre 2024", None),
        ("October 7, 24", None),
        ("2024-2-9", None),
        ("Oct. 7, \uff12\uff10\uff12\uff14", None),
        ("Release date: Oct. 7, 2024", None),
        ("0001-01-01", None),
        ("", None),
    ],
)
def test_only_complete_unambiguous_calendar_dates_supply_years(value, year):
    assert calendar_year(value) == year


def test_observed_literals_prepare_both_proofs_without_changing_facts():
    candidate, page = example()
    original, original_page = candidate.model_dump(), page.model_dump()
    task = TaskSpec(identity_fields=["/version"])
    assert verify(candidate, page, SCHEMA, task) == ["/version:unsupported_value"]
    prepared, changes = prepare_candidate_proofs(candidate, page, task, SEMANTICS)
    assert candidate.model_dump() == original
    assert page.model_dump() == original_page
    assert prepared.record == candidate.record and prepared.scope == candidate.scope
    assert prepared.evidence["/version"].quote == "9.1.0"
    assert prepared.temporal_evidence["/release_date"].model_dump() == {
        "source": "date",
        "quote": "Oct. 7, 2024",
        "reference_year": 2024,
    }
    assert [change["kind"] for change in changes] == [
        "narrow_text_quote",
        "event_date_reference_year",
    ]
    assert changes[0]["before"] == original["evidence"]["/version"]
    assert changes[0]["after"] == prepared.evidence["/version"].model_dump()
    assert verify(prepared, page, SCHEMA, task) == []
    assert (
        temporal_errors(
            prepared,
            page,
            SCHEMA,
            TemporalIntent(mode="latest"),
            current_year=2026,
            field_semantics=SEMANTICS,
        )
        == []
    )
    unchanged, repeated = prepare_candidate_proofs(prepared, page, task, SEMANTICS)
    assert unchanged is prepared and repeated == []


@pytest.mark.parametrize(
    "change",
    [
        "null",
        "number",
        "empty",
        "blank",
        "missing_proof",
        "wrong_transform",
        "missing_source",
        "link_source",
        "wrong_scope",
        "unobserved_quote",
        "empty_quote",
        "invented_value",
        "partial_word",
        "partial_number",
        "quote_from_other_source",
    ],
)
def test_unsupported_values_and_bindings_are_not_repaired(change):
    candidate, page = example()
    candidate.record = {"version": "9.1.0"}
    candidate.evidence.pop("/release_date")
    source = page.sources[0]
    proof = candidate.evidence["/version"]
    if change in {"null", "number", "empty", "blank"}:
        candidate.record["version"] = {"null": None, "number": 9, "empty": "", "blank": " \n "}[
            change
        ]
    elif change == "missing_proof":
        candidate.evidence.clear()
    elif change == "wrong_transform":
        proof.transform = "number"
    elif change == "missing_source":
        proof.source = "absent"
    elif change == "link_source":
        source.kind = "link"
    elif change == "wrong_scope":
        source.scope = "different-record"
    elif change == "unobserved_quote":
        proof.quote = "Unobserved 9.1.0"
    elif change == "empty_quote":
        proof.quote = ""
    elif change == "invented_value":
        candidate.record["version"] = "Runtime 9.1.0, invented suffix"
    elif change == "partial_word":
        candidate.record["version"] = "time"
    elif change == "partial_number":
        source.text = proof.quote = "Runtime 19.1.00"
    elif change == "quote_from_other_source":
        source.text = "Other release"
        page.sources[1].text = proof.quote
    before = candidate.model_dump()
    prepared, changes = prepare_candidate_proofs(candidate, page, TaskSpec(), {})
    assert prepared is candidate and prepared.model_dump() == before and changes == []


@pytest.mark.parametrize(
    "rule",
    [
        FieldRule(source="page_url"),
        FieldRule(source="link"),
        FieldRule(external=True),
        FieldRule(mapping={'"9.1.0"': "Runtime 9.1.0"}),
    ],
)
def test_explicit_field_rules_remain_authoritative(rule):
    candidate, page = example()
    prepared, changes = prepare_candidate_proofs(
        candidate, page, TaskSpec(field_rules={"/version": rule, "/release_date": rule}), SEMANTICS
    )
    assert prepared is candidate and changes == []


@pytest.mark.parametrize("kind", ["asset", "projection", "duplicate_source_id"])
def test_dataset_proofs_and_ambiguous_source_ids_are_untouched(kind):
    candidate, page = example()
    if kind == "asset":
        page.dataset_asset_id = "asset"
    elif kind == "projection":
        page.dataset_projection = ProjectionPlan(
            fields=[{"source": "/version", "target": "/version"}]
        )
    else:
        page.sources.append(page.sources[0].model_copy(deep=True))
    prepared, changes = prepare_candidate_proofs(candidate, page, TaskSpec(), SEMANTICS)
    assert prepared is candidate and changes == []


@pytest.mark.parametrize(
    "field",
    [
        None,
        FieldSemantics(
            pointer="/release_date", temporal_class="static", reference_period="required"
        ),
        FieldSemantics(
            pointer="/release_date", temporal_class="mutable", reference_period="required"
        ),
        FieldSemantics(pointer="/release_date", temporal_class="event", reference_period="none"),
    ],
)
def test_no_year_inference_without_an_event_reference_policy(field):
    candidate, page = example()
    candidate.evidence["/version"].quote = "9.1.0"
    semantics = {} if field is None else {field.pointer: field}
    prepared, changes = prepare_candidate_proofs(candidate, page, TaskSpec(), semantics)
    assert prepared is candidate and changes == []


def test_existing_wrong_temporal_proof_is_preserved_for_rejection():
    candidate, page = example()
    candidate.evidence["/version"].quote = "9.1.0"
    candidate.temporal_evidence = Candidate.model_validate(
        {
            **candidate.model_dump(),
            "temporal_evidence": {
                "/release_date": {
                    "source": "date",
                    "quote": "Oct. 7, 2024",
                    "reference_year": 2025,
                },
            },
        }
    ).temporal_evidence
    prepared, changes = prepare_candidate_proofs(candidate, page, TaskSpec(), SEMANTICS)
    assert prepared is candidate and changes == []
    assert temporal_errors(
        prepared,
        page,
        SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
        field_semantics=SEMANTICS,
    ) == [
        "/release_date:temporal_quote_not_observed",
    ]


@pytest.mark.parametrize("value", ["2024", "2024-2025", "03/04/2024", "Oct. 32, 2024"])
def test_ambiguous_or_invalid_date_values_remain_missing_temporal_proof(value):
    candidate, page = example()
    candidate.evidence["/version"].quote = "9.1.0"
    candidate.record["release_date"] = value
    candidate.evidence["/release_date"].quote = page.sources[1].text = value
    prepared, changes = prepare_candidate_proofs(candidate, page, TaskSpec(), SEMANTICS)
    assert prepared is candidate and changes == []
    assert temporal_errors(
        prepared,
        page,
        SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2026,
        field_semantics=SEMANTICS,
    ) == [
        "/release_date:missing_temporal_evidence",
    ]


def test_year_and_future_policies_still_reject_prepared_dates():
    candidate, page = example()
    prepared, _ = prepare_candidate_proofs(candidate, page, TaskSpec(), SEMANTICS)
    assert temporal_errors(
        prepared,
        page,
        SCHEMA,
        TemporalIntent(mode="year", start_year=2025),
        current_year=2026,
        field_semantics=SEMANTICS,
    ) == [
        "/release_date:temporal_mismatch",
    ]
    assert temporal_errors(
        prepared,
        page,
        SCHEMA,
        TemporalIntent(mode="latest"),
        current_year=2023,
        field_semantics=SEMANTICS,
    ) == [
        "/release_date:future_temporal_value",
    ]


def test_nested_array_event_dates_and_whitespace_preserve_raw_values():
    candidate, page = example()
    value = "  7  October\n2024  "
    candidate.record = {"events": [{"when": value}]}
    candidate.evidence = {"/events/0/when": candidate.evidence["/release_date"]}
    candidate.evidence["/events/0/when"].quote = "Date: 7 October 2024"
    page.sources[1].text = "Date: 7 October 2024"
    schema = {
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "when": {
                            "type": "string",
                            "x-verboisy-temporal-class": "event",
                            "x-verboisy-reference-period": "preferred",
                        }
                    },
                },
            }
        }
    }
    before = deepcopy(candidate.record)
    prepared, changes = prepare_candidate_proofs(
        candidate, page, TaskSpec(), build_field_semantics(schema)
    )
    assert len(changes) == 2
    assert prepared.record == before and candidate.record == before
    assert prepared.temporal_evidence["/events/0/when"].reference_year == 2024
    assert verify(prepared, page, schema, TaskSpec()) == []
