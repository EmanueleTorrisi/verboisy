# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Strict boundaries for user policy and untrusted model output."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from verboisy.dataset_formats import DatasetFormat
from verboisy.time_series_contract import TimeSeriesSpec


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProjectionField(StrictModel):
    source: str = Field(min_length=1, max_length=8192)
    target: str = Field(min_length=1, max_length=8192)
    conversion: Literal[
        "identity", "integer", "number", "boolean", "string", "date_iso", "date_dmy", "date_mdy"
    ] = "identity"


class UnitProjectionField(StrictModel):
    source: str = Field(min_length=1, max_length=8192)
    target: str = Field(min_length=1, max_length=8192)
    conversion: Literal["unit_base"]
    unit_source: str = Field(min_length=1, max_length=8192)


class DescriptorBinding(StrictModel):
    kind: Literal["definition", "methodology"]
    source: str = Field(min_length=1, max_length=8192)


class DescribedProjectionField(ProjectionField):
    descriptors: list[DescriptorBinding] = Field(min_length=1, max_length=2)


class DescribedUnitProjectionField(UnitProjectionField):
    descriptors: list[DescriptorBinding] = Field(min_length=1, max_length=2)


class TemporalProjectionField(ProjectionField):
    reference_year_source: str = Field(min_length=1, max_length=8192)


class TemporalUnitProjectionField(UnitProjectionField):
    reference_year_source: str = Field(min_length=1, max_length=8192)


class TemporalDescribedProjectionField(DescribedProjectionField):
    reference_year_source: str = Field(min_length=1, max_length=8192)


class TemporalDescribedUnitProjectionField(DescribedUnitProjectionField):
    reference_year_source: str = Field(min_length=1, max_length=8192)


class ProjectionPlan(StrictModel):
    version: Literal["1"] = "1"
    fields: list[
        ProjectionField
        | UnitProjectionField
        | DescribedProjectionField
        | DescribedUnitProjectionField
        | TemporalProjectionField
        | TemporalUnitProjectionField
        | TemporalDescribedProjectionField
        | TemporalDescribedUnitProjectionField
    ] = Field(min_length=1, max_length=100)


class Source(StrictModel):
    id: str
    kind: Literal["text", "link"]
    text: str
    scope: str
    href: str | None = None


class Snapshot(StrictModel):
    id: str
    url: str
    fetched_at: str
    content_hash: str
    sources: list[Source]
    truncated: bool
    dataset_asset_id: str | None = None
    dataset_row_index: int | None = Field(default=None, ge=1)
    dataset_projection: ProjectionPlan | None = None
    dataset_source_row_json: str | None = None


class Proof(StrictModel):
    source: str
    quote: str = ""
    transform: Literal[
        "text", "number", "integer", "boolean", "href", "page_url", "dataset", "dataset_projection"
    ] = "text"


class TemporalProof(StrictModel):
    source: str
    quote: str
    reference_year: int = Field(ge=1000, le=9999)


class Candidate(StrictModel):
    scope: str
    record: dict[str, Any]
    evidence: dict[str, Proof]
    temporal_evidence: dict[str, TemporalProof] = Field(default_factory=dict)


class RangeConflict(StrictModel):
    pointer: str = Field(min_length=1, max_length=8192)
    scope: str = Field(min_length=1, max_length=8192)
    source: str = Field(min_length=1, max_length=8192)
    quote: str = Field(min_length=1, max_length=1000)


class ResearchSuggestion(StrictModel):
    goal: str | None = Field(default=None, min_length=1, max_length=1000)
    columns: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=10)
    drop_columns: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[RangeConflict] = Field(min_length=1, max_length=20)


class PageProposal(StrictModel):
    candidates: list[Candidate] = Field(max_length=100)
    priority_links: list[str] = Field(default_factory=list, max_length=100)
    range_conflicts: list[RangeConflict] = Field(default_factory=list, max_length=20)
    research_suggestions: list[ResearchSuggestion] = Field(default_factory=list, max_length=3)


class Review(StrictModel):
    relevant: bool
    same_entity: bool
    supported_fields: list[str]
    rejected_fields: list[str]


class FieldRule(StrictModel):
    source: Literal["auto", "link", "page_url"] = "auto"
    external: bool = False
    mapping: dict[str, str] = Field(default_factory=dict)


class DatasetSource(StrictModel):
    url: str = Field(min_length=1, max_length=8192)
    format: DatasetFormat
    projection: ProjectionPlan | None = None


class TaskSpec(StrictModel):
    time_series: TimeSeriesSpec | None = None
    dataset_sources: list[DatasetSource] = Field(default_factory=list, max_length=100)
    seed_urls: list[str] = Field(default_factory=list, max_length=100)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=100)
    avoided_hosts: list[str] = Field(default_factory=list, max_length=100)
    include_paths: list[str] = Field(default_factory=list, max_length=100)
    exclude_paths: list[str] = Field(default_factory=list, max_length=100)
    target_records: int | None = Field(default=None, gt=0, le=100000)
    identity_fields: list[str] = Field(default_factory=list, max_length=20)
    field_rules: dict[str, FieldRule] = Field(default_factory=dict)
    max_depth: int = Field(default=3, ge=0, le=20)
    max_pages: int = Field(default=100, gt=0, le=10000)
    max_links_per_page: int = Field(default=200, gt=0, le=5000)
    max_interactions_per_page: int = Field(default=2, ge=0, le=20)
    pagination_selector: str | None = None
    settle_ms: int = Field(default=750, ge=0, le=10000)
    allow_nulls: bool = True
    csv_mode: Literal["json", "spreadsheet"] = "json"

    @model_validator(mode="after")
    def valid_series_identity(self) -> "TaskSpec":
        if self.time_series is not None:
            self.time_series.validate_identity(self.identity_fields)
        return self
