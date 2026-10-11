# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Chronology, explicit timezone policy and public export recovery contracts."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from verboisy.api import arun
from verboisy.evidence.models import TaskSpec
from verboisy.llm.client import LLMClient
from verboisy.research_summary import summarize_fields
from verboisy.storage.research import ResearchStore
from verboisy.time_series import (
    TimeSeriesSpec,
    inspect_time_series,
    timestamp_key,
    validate_time_series,
)
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "01/02/2026",
        "2026-02-30",
        "2026-01-01",
        "2026-01-01T00:00:00",
        "2026-01-01T24:00:00Z",
        "2026-01-01T00:00:00+99:00",
        "9999-12-31T23:59:59-01:00",
    ],
)
def test_unusable_instants_remain_uninterpreted(value):
    assert timestamp_key(value, TimeSeriesSpec(timestamp_field="observed")) is None


@pytest.mark.parametrize("value", ["2026-10-25T02:30:00", "2026-03-29T02:30:00"])
def test_dst_fold_and_nonexistent_local_clock_rejected(value):
    spec = TimeSeriesSpec(timestamp_field="t", assume_timezone="Europe/Rome")
    assert timestamp_key(value, spec) is None


def test_explicit_timezone_and_offset_equivalence():
    spec = TimeSeriesSpec(timestamp_field="t", assume_timezone="Europe/Rome")
    assert timestamp_key("2026-01-01T09:00:00", spec) == timestamp_key("2026-01-01T08:00:00Z", spec)
    assert timestamp_key("2026-10-25T02:30:00+02:00", spec) != timestamp_key(
        "2026-10-25T02:30:00+01:00", spec
    )
    assert timestamp_key("2026-01-01T00:00:00.000001Z", spec) + 1 == timestamp_key(
        "2026-01-01T00:00:00.000002Z", spec
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"timestamp_field": " "},
        {"timestamp_field": "id"},
        {"series_fields": ["t"]},
        {"series_fields": ["station", "station"]},
        {"series_fields": [""]},
        {"series_fields": ["x" * 101]},
        {"assume_timezone": "not/a-zone"},
        {"assume_timezone": "/tmp"},
        {"interval_seconds": 0},
        {"interval_seconds": True},
        {"timestamp_kind": "date", "assume_timezone": "UTC"},
        {"timestamp_kind": "date", "interval_seconds": 3600},
        {"unknown": True},
    ],
)
def test_strict_policy(extra):
    with pytest.raises(ValidationError):
        TimeSeriesSpec.model_validate({"timestamp_field": "t", **extra})


def test_dates_are_calendar_days_without_locale_inference():
    spec = TimeSeriesSpec(timestamp_field="t", timestamp_kind="date", interval_seconds=86400)
    assert (
        timestamp_key("2024-03-01", spec) - timestamp_key("2024-02-28", spec) == 2 * 86400 * 1000000
    )
    assert timestamp_key("03/01/2024", spec) is None
    assert timestamp_key("2024-02-30", spec) is None


@pytest.mark.parametrize(
    "group,order,fields", [("station", False, ["t"]), (None, True, ["t"]), (None, False, ["other"])]
)
def test_conflicting_shaping_is_rejected(group, order, fields):
    with pytest.raises(VerboisyError):
        validate_time_series(TimeSeriesSpec(timestamp_field="t"), fields, group, order)
    validate_time_series(None, [], group, order)


def test_offset_chronology_groups_duplicates_and_gaps():
    rows = [
        {"id": "later", "station": "A", "t": "2026-01-01T08:00:00Z"},
        {"id": "early", "station": "A", "t": "2026-01-01T09:00:00+02:00"},
        {"id": "duplicate", "station": "A", "t": "2026-01-01T07:00:00Z"},
        {"id": "gap", "station": "A", "t": "2026-01-01T10:00:00Z"},
        {"id": "off-grid", "station": "B", "t": "2026-01-01T07:30:00Z"},
        {"id": "start", "station": "B", "t": "2026-01-01T07:00:00Z"},
        {"id": "invalid", "station": "B", "t": None},
        {"id": "no-series", "t": "2026-01-01T07:00:00Z"},
    ]
    before = json.dumps(rows)
    ordered, report, notices = inspect_time_series(
        rows, TimeSeriesSpec(timestamp_field="t", series_fields=["station"], interval_seconds=3600)
    )
    assert [row["id"] for row in ordered] == [
        "early",
        "duplicate",
        "later",
        "gap",
        "start",
        "off-grid",
        "invalid",
        "no-series",
    ]
    assert report["counts"] == {
        "invalid_timestamp": 1,
        "invalid_series": 1,
        "duplicate_instant": 1,
        "missing_observations": 1,
        "off_grid_intervals": 1,
    }
    assert report["series_count"] == 2 and len(notices) == 2
    assert json.dumps(rows) == before
    assert report["interpolation_applied"] is report["endpoint_coverage_claimed"] is False


def test_large_gap_is_arithmetic_and_examples_are_bounded():
    spec = TimeSeriesSpec(timestamp_field="t", interval_seconds=1)
    rows = [{"t": "2000-01-01T00:00:00Z"}, {"t": "2026-01-01T00:00:00Z"}] + [{"t": None}] * 30
    ordered, report, _ = inspect_time_series(rows, spec)
    assert len(ordered) == 32 and len(report["examples"]) == 20
    assert report["counts"]["missing_observations"] > 800000000
    assert inspect_time_series([], spec)[1]["series_count"] == 0


def test_cadence_not_inferred_and_typed_series_remain_distinct():
    spec = TimeSeriesSpec(timestamp_field="t", series_fields=["station"])
    rows = [{"t": "2026-01-01T00:00:00Z", "station": v} for v in (1, True, "1", None, [])]
    _, report, _ = inspect_time_series(rows, spec)
    assert report["series_count"] == 3 and report["counts"]["invalid_series"] == 2
    with pytest.raises(VerboisyError):
        inspect_time_series([{"t": "2026-01-01T00:00:00Z", "station": float("nan")}], spec)
    _, clean, notices = inspect_time_series(rows[:1], spec)
    assert not any(clean["counts"].values()) and len(notices) == 1
    _, sparse, _ = inspect_time_series(
        [
            {"t": "2026-01-01T00:00:00Z", "station": "A"},
            {"t": "2026-01-03T00:00:00Z", "station": "A"},
        ],
        spec,
    )
    assert sparse["counts"]["missing_observations"] == 0


def test_identity_must_distinguish_series_observations():
    policy = {"timestamp_field": "t", "series_fields": ["station"]}
    with pytest.raises(ValidationError, match="identity must include"):
        TaskSpec(time_series=policy, identity_fields=["/station"])
    assert TaskSpec(time_series=policy, identity_fields=["/station", "/t"]).time_series is not None
    with pytest.raises(VerboisyError, match="identity must include"):
        validate_time_series(TimeSeriesSpec(**policy), ["t", "station"], None, False, ["/station"])
    escaped = TimeSeriesSpec(timestamp_field="a/b", series_fields=["a~b"])
    escaped.validate_identity(["/a~1b", "/a~0b"])


def test_coverage_summary_is_scoped_and_bounded():
    report, notices = summarize_fields([{"name": "Example", "country": None}], ["name", "country"])
    assert report["non_null_counts"] == {"name": 1, "country": 0}
    assert "not all possible sources" in notices[0] and notices[0].startswith("*")
    assert summarize_fields([], ["country"])[1] == []
    assert summarize_fields([{"n": 0, "b": False, "text": ""}], ["n", "b", "text"])[1] == []


@pytest.mark.asyncio
async def test_local_series_export_resume_preserves_raw_evidence(tmp_path, monkeypatch):
    provider = AsyncMock(side_effect=AssertionError("No paid calls for local preparation"))
    monkeypatch.setattr(LLMClient, "complete_json", provider)
    monkeypatch.setattr("verboisy.api.web_search", provider)
    source = tmp_path / "observations.jsonl"
    raw = [
        {"station": "A", "t": "2026-01-01T08:00:00Z", "mass": "100 - 120 lb", "missing": None},
        {"station": "A", "t": "2026-01-01T09:00:00+02:00", "mass": "45 - 55 kg", "missing": None},
        {"station": "A", "t": "2026-01-01T10:00:00Z", "mass": "50 - 60 kg", "missing": None},
    ]
    source.write_text("\n".join(json.dumps(row) for row in raw))
    schema = {
        "type": "object",
        "properties": {key: {"type": ["string", "null"]} for key in raw[0]},
        "required": list(raw[0]),
    }
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "runs.db"),
        dataset_local_roots=[str(tmp_path)],
        search_provider="disabled",
    )
    task = TaskSpec(
        dataset_sources=[{"url": source.as_uri(), "format": "jsonl"}],
        target_records=3,
        time_series={
            "timestamp_field": "t",
            "series_fields": ["station"],
            "interval_seconds": 3600,
        },
    )
    destination = tmp_path / "rows.json"
    result = await arun(
        goal="Explicit observations",
        schema=schema,
        task=task,
        config=config,
        export=destination,
        date_format="iso",
    )
    assert result.completed and result.records[0]["t"] == raw[1]["t"]
    manifest = json.loads(destination.with_suffix(".json.manifest.json").read_text())
    assert manifest["time_series"]["counts"]["missing_observations"] == 1
    assert manifest["field_coverage"]["non_null_counts"]["missing"] == 0
    assert len(manifest["output_lineage"]) == 3
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    evidence = store.evidence(result.run_id)
    store.close()
    source.unlink()
    resumed = await arun(resume=result.run_id, config=config, mass_unit="lb")
    assert resumed.completed and resumed.records[0]["mass"].endswith(" lb")
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    assert store.evidence(result.run_id) == evidence
    store.close()
    assert provider.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"order": [("t", "asc")]}, {"groupby": "t"}])
async def test_api_rejects_conflicting_series_before_acquisition(tmp_path, monkeypatch, kwargs):
    provider = AsyncMock(side_effect=AssertionError("No acquisition"))
    monkeypatch.setattr(LLMClient, "complete_json", provider)
    with pytest.raises(VerboisyError, match="Time-series ordering"):
        await arun(
            goal="Example",
            schema={"type": "object", "properties": {"t": {"type": "string"}}},
            task={"time_series": {"timestamp_field": "t"}},
            config=Settings(_env_file=None, sqlite_db_path=str(tmp_path / "r.db")),
            **kwargs,
        )
    assert provider.await_count == 0
