"""Strict boundaries for user policy and untrusted model output."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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


class Proof(StrictModel):
    source: str
    quote: str = ""
    transform: Literal["text", "number", "integer", "boolean", "href", "page_url"] = "text"


class Candidate(StrictModel):
    scope: str
    record: dict[str, Any]
    evidence: dict[str, Proof]


class PageProposal(StrictModel):
    candidates: list[Candidate] = Field(max_length=100)
    priority_links: list[str] = Field(default_factory=list, max_length=100)


class Review(StrictModel):
    relevant: bool
    same_entity: bool
    supported_fields: list[str]
    rejected_fields: list[str]


class FieldRule(StrictModel):
    source: Literal["auto", "link", "page_url"] = "auto"
    external: bool = False
    mapping: dict[str, str] = Field(default_factory=dict)


class TaskSpec(StrictModel):
    seed_urls: list[str] = Field(default_factory=list, max_length=100)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=100)
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
