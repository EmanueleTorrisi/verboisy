# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Validate saved product settings before resume can publish a user decision."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verboisy.product import SourcePolicy
from verboisy.storage.json_payload import decode_saved_json
from verboisy.utils.exceptions import VerboisyError


class _SavedModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _SortKey(_SavedModel):
    field: str = Field(min_length=1)
    direction: Literal["asc", "desc"] = "asc"


class _SourcePolicy(_SavedModel):
    include: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    onlyinclude: bool = False


class _ProductOptions(_SavedModel):
    strings: bool = False
    groupby: str | None = None
    smartid: str | None = None
    proof: bool = False
    research: bool = False
    schema_inferred: bool = False
    order: list[_SortKey] = Field(default_factory=list)
    source_policy: _SourcePolicy = Field(default_factory=_SourcePolicy)


def saved_product_options(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Read the latest options with legacy defaults and no truthiness coercion.

    Unconsumed historical extension fields remain ignored. This is a validation
    boundary, not a migration: returned defaults do not modify the saved event.
    """
    try:
        value = _ProductOptions.model_validate(events[-1]["payload"] if events else {})
        if any(not key.field.strip() for key in value.order):
            raise ValueError("Empty sort field")
        for text in (value.groupby, value.smartid):
            if text is not None and not text.strip():
                raise ValueError("Empty shaping field")
        policy = value.source_policy
        SourcePolicy(tuple(policy.include), tuple(policy.avoid), policy.onlyinclude)
    except (ValidationError, ValueError, TypeError, KeyError, VerboisyError):
        raise VerboisyError("Saved product options failed integrity verification") from None
    return value.model_dump(mode="json")


def saved_export_destinations(payload: str | None) -> str | list[str] | None:
    """Decode inherited destinations without accepting object keys as path lists."""
    if payload is None or payload == "":
        return None
    try:
        value = decode_saved_json(payload)
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(path, str) for path in value):
            return value
        raise ValueError("Invalid saved export destinations")
    except (ValueError, TypeError):
        raise VerboisyError("Saved export destinations failed integrity verification") from None
