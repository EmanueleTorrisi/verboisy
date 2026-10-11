# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Display choices shared by settings, run persistence and export formatting."""

from typing import Any, Literal

from pydantic import ValidationError

from verboisy.evidence.models import StrictModel
from verboisy.utils.exceptions import VerboisyError

MassUnit = Literal["kg", "lb", "source"]
LengthUnit = Literal["m", "ft", "source"]
DateFormat = Literal["dmy", "mdy", "iso", "source"]


class PresentationPreferences(StrictModel):
    mass_unit: MassUnit = "kg"
    length_unit: LengthUnit = "m"
    date_format: DateFormat = "dmy"


def preferences(value: Any) -> PresentationPreferences:
    """Reject unsupported choices without echoing untrusted configuration values."""
    try:
        return PresentationPreferences.model_validate(value)
    except ValidationError:
        raise VerboisyError(
            "Display preferences: mass-unit kg/lb/source; length-unit m/ft/source; "
            "date-format dmy/mdy/iso/source"
        ) from None


def resolve_preferences(
    defaults: PresentationPreferences,
    saved: dict[str, Any] | None,
    overrides: dict[str, Any],
) -> PresentationPreferences:
    """Explicit options override saved choices; settings fill unsaved choices.

    A completed run's display must remain stable when its environment changes.
    New defaults take effect on new runs, or fields absent from an older snapshot.
    """
    if saved is not None:
        # Validate the historical entry before overrides can hide damaged fields.
        preferences(saved)
    return preferences(
        {**defaults.model_dump(), **(saved if saved is not None else {}), **overrides}
    )


def resolve_saved_preferences(
    defaults: PresentationPreferences,
    events: list[dict[str, Any]],
    overrides: dict[str, Any],
) -> PresentationPreferences:
    """Distinguish absent history from a malformed latest saved display entry."""
    saved = events[-1]["payload"] if events else None
    if events and saved is None:
        preferences(saved)
    return resolve_preferences(defaults, saved, overrides)
