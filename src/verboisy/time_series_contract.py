# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Standalone policy types shared by task parsing and observation inspection."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeSeriesSpec(BaseModel):
    """A saved, explicit row-time contract; cadence is fixed elapsed seconds."""

    model_config = ConfigDict(extra="forbid", strict=True)
    timestamp_field: str = Field(min_length=1, max_length=100)
    timestamp_kind: Literal["date", "date-time"] = "date-time"
    series_fields: list[str] = Field(default_factory=list, max_length=10)
    assume_timezone: str | None = Field(default=None, min_length=1, max_length=100)
    interval_seconds: int | None = Field(default=None, gt=0, le=315_576_000)

    @model_validator(mode="after")
    def valid_contract(self) -> "TimeSeriesSpec":
        names = [self.timestamp_field, *self.series_fields]
        if any(not name.strip() or name == "id" or len(name) > 100 for name in names):
            raise ValueError("Time-series fields must be nonempty source column names")
        if len(set(names)) != len(names):
            raise ValueError("Time-series fields must be distinct")
        if self.timestamp_kind == "date" and (
            self.assume_timezone is not None
            or self.interval_seconds is not None
            and self.interval_seconds % 86400
        ):
            raise ValueError("Calendar dates use whole-day cadence and no timezone")
        if self.assume_timezone is not None:
            try:
                ZoneInfo(self.assume_timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Time-series timezone is unavailable") from None
        return self

    def validate_identity(self, identity_fields: list[str]) -> None:
        """A declared identity must distinguish stations and observation times."""
        required = {
            "/" + name.replace("~", "~0").replace("/", "~1")
            for name in [self.timestamp_field, *self.series_fields]
        }
        if identity_fields and not required <= set(identity_fields):
            raise ValueError("Time-series identity must include timestamp and series fields")
