# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Tests for deterministic research planning."""

import pytest
from verboisy.core.planner import (
    build_research_plan,
)


def array_schema(*fields):
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {field: {"type": "string"} for field in fields},
        },
    }


def test_small_bounded_dataset_plan():
    plan = build_research_plan(
        array_schema(
            "name",
            "population_count",
            "area_amount",
        ),
        5,
    )

    assert plan.task_shape == "bounded_list"
    assert plan.initial_source_goal == 3
    assert plan.probe_batches == 2
    assert plan.rejection_cutoff == 5

    assert plan.field_terms == (
        "area",
        "name",
        "population",
    )


@pytest.mark.parametrize(
    ("target", "sources", "batches", "cutoff"),
    [
        (25, 5, 3, 12),
        (500, 8, 4, 20),
    ],
)
def test_larger_bounded_dataset_plans(
    target,
    sources,
    batches,
    cutoff,
):
    plan = build_research_plan(
        array_schema("company"),
        target,
    )

    assert plan.task_shape == "bounded_list"
    assert plan.initial_source_goal == sources
    assert plan.probe_batches == batches
    assert plan.rejection_cutoff == cutoff


def test_open_list_plan():
    plan = build_research_plan(
        array_schema("company"),
        None,
    )

    assert plan.task_shape == "open_list"
    assert plan.initial_source_goal == 8
    assert plan.probe_batches == 4
    assert plan.rejection_cutoff == 20


def test_single_record_plan():
    plan = build_research_plan(
        {
            "type": "object",
            "properties": {
                "companyName": {
                    "type": "string",
                }
            },
        },
        None,
    )

    assert plan.task_shape == "single_record"
    assert plan.initial_source_goal == 3
    assert plan.probe_batches == 2
    assert plan.rejection_cutoff == 4
    assert plan.field_terms == (
        "company",
        "name",
    )


def test_source_scoring_rewards_schema_and_structure():
    plan = build_research_plan(
        array_schema(
            "name",
            "capital",
            "population_count",
            "area_amount",
        ),
        5,
    )

    useful = plan.source_score(
        "Countries population capital area table",
        "https://example.com/country-statistics",
    )

    vague = plan.source_score(
        "World geography",
        "https://example.com/",
    )

    low_value = plan.source_score(
        "Countries population table",
        "https://www.scribd.com/document/123",
    )

    assert useful > vague
    assert low_value < useful


def test_plan_event_is_serializable_shape():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    assert plan.as_event() == {
        "task_shape": "bounded_list",
        "target_records": 5,
        "field_terms": ("name",),
        "initial_source_goal": 3,
        "probe_batches": 2,
        "rejection_cutoff": 5,
    }


def test_source_scoring_rewards_schema_term_in_url():
    plan = build_research_plan(
        array_schema("population"),
        5,
    )

    score = plan.source_score(
        "Countries",
        "https://example.com/population-data",
    )

    assert score >= 2


def test_unproductive_page_probe_stops_after_threshold():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    assert plan.should_stop_unproductive_page(
        batches_seen=2,
        accepted=0,
        rejected=5,
    )


def test_unproductive_page_probe_keeps_going_when_too_early():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    assert not plan.should_stop_unproductive_page(
        batches_seen=1,
        accepted=0,
        rejected=5,
    )


def test_unproductive_page_probe_keeps_productive_page():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    assert not plan.should_stop_unproductive_page(
        batches_seen=10,
        accepted=1,
        rejected=50,
    )


def test_unproductive_page_probe_requires_enough_rejections():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    assert not plan.should_stop_unproductive_page(
        batches_seen=10,
        accepted=0,
        rejected=4,
    )


def test_evidence_score_prefers_requested_schema_coverage():
    plan = build_research_plan(
        array_schema(
            "name",
            "capital",
            "population_count",
            "area_amount",
        ),
        5,
    )

    useful = plan.evidence_score(
        "Country population capital area statistics table",
        source_count=12,
    )
    navigation = plan.evidence_score(
        "Home About Contact Privacy",
        source_count=40,
    )

    assert useful > navigation


def test_evidence_score_uses_density_as_tiebreaker():
    plan = build_research_plan(
        array_schema("population"),
        5,
    )

    sparse = plan.evidence_score(
        "unrelated content",
        source_count=1,
    )
    dense = plan.evidence_score(
        "unrelated content",
        source_count=20,
    )

    assert dense > sparse


def test_bounded_plan_activates_only_initial_source_budget():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    active, deferred = plan.split_initial_sources(
        [
            "https://one.test/",
            "https://two.test/",
            "https://three.test/",
            "https://four.test/",
            "https://five.test/",
        ]
    )

    assert active == [
        "https://one.test/",
        "https://two.test/",
        "https://three.test/",
    ]
    assert deferred == [
        "https://four.test/",
        "https://five.test/",
    ]


def test_open_list_plan_keeps_all_initial_sources_active():
    plan = build_research_plan(
        array_schema("name"),
        None,
    )

    urls = [
        "https://one.test/",
        "https://two.test/",
        "https://three.test/",
    ]

    active, deferred = plan.split_initial_sources(urls)

    assert active == urls
    assert deferred == []


def test_initial_source_partition_handles_short_list():
    plan = build_research_plan(
        array_schema("name"),
        5,
    )

    urls = [
        "https://one.test/",
        "https://two.test/",
    ]

    active, deferred = plan.split_initial_sources(urls)

    assert active == urls
    assert deferred == []


def test_source_productivity_score_is_smoothed_around_neutral():
    from verboisy.core.planner import source_productivity_score

    assert source_productivity_score(0, 0) == 0
    assert source_productivity_score(1, 0) > 0
    assert source_productivity_score(0, 1) < 0
    assert source_productivity_score(1, 1) == 0


def test_temporal_intent_defaults_to_latest():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Find the population of Canada",
        current_year=2026,
    )

    assert intent.mode == "latest"
    assert intent.start_year is None
    assert intent.end_year is None


def test_temporal_intent_explicit_year():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Find Canada's population in 1974",
        current_year=2026,
    )

    assert intent.mode == "year"
    assert intent.start_year == 1974
    assert intent.end_year == 1974


def test_temporal_intent_explicit_range():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Population from 1990 to 2000",
        current_year=2026,
    )

    assert intent.mode == "range"
    assert intent.start_year == 1990
    assert intent.end_year == 2000


def test_temporal_intent_full_decade():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Population during the 1970s",
        current_year=2026,
    )

    assert intent.mode == "range"
    assert intent.start_year == 1970
    assert intent.end_year == 1979


def test_temporal_intent_short_decade():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Population in the 70s",
        current_year=2026,
    )

    assert intent.mode == "range"
    assert intent.start_year == 1970
    assert intent.end_year == 1979


def test_temporal_intent_current_century_short_decade():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Population in the 20s",
        current_year=2026,
    )

    assert intent.mode == "range"
    assert intent.start_year == 2020
    assert intent.end_year == 2029


def test_temporal_intent_series():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Show population year by year",
        current_year=2026,
    )

    assert intent.mode == "series"
    assert intent.start_year is None
    assert intent.end_year is None


def test_temporal_intent_reversed_range_is_normalized():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Population from 2000 to 1990",
        current_year=2026,
    )

    assert intent.start_year == 1990
    assert intent.end_year == 2000


def test_temporal_intent_serializes_for_events():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Latest population",
        current_year=2026,
    )

    assert intent.as_event() == {
        "mode": "latest",
        "start_year": None,
        "end_year": None,
    }


def test_temporal_intent_multiple_unstructured_years_becomes_range():
    from verboisy.core.planner import infer_temporal_intent

    intent = infer_temporal_intent(
        "Compare population in 1990 versus population in 2000",
        current_year=2026,
    )

    assert intent.mode == "range"
    assert intent.start_year == 1990
    assert intent.end_year == 2000
