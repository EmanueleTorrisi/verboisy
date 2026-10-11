# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Dates require an explicit exact format and valid Gregorian calendar values."""

import json

import pytest
from pydantic import ValidationError
from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.projection import ProjectionError, project_row


def convert(value, mode):
    data = parse_dataset(json.dumps([{"raw": value}]).encode(), "json")
    plan = ProjectionPlan.model_validate(
        {"fields": [{"source": "/raw", "target": "/date", "conversion": mode}]}
    )
    return data, project_row(data.rows[0], plan)


@pytest.mark.parametrize(
    "mode,value,expected",
    [
        ("date_iso", "2024-02-29", "2024-02-29"),
        ("date_iso", "0001-01-01", "0001-01-01"),
        ("date_iso", "9999-12-31", "9999-12-31"),
        ("date_dmy", "29/02/2024", "2024-02-29"),
        ("date_mdy", "02/29/2024", "2024-02-29"),
        ("date_dmy", "03/04/2025", "2025-04-03"),
        ("date_mdy", "03/04/2025", "2025-03-04"),
        ("date_iso", None, None),
        ("date_dmy", None, None),
        ("date_mdy", None, None),
    ],
)
def test_declared_dates_and_nulls_preserve_raw_derivation(mode, value, expected):
    data, projected = convert(value, mode)
    assert projected.values == {"date": expected}
    assert data.rows[0].values == {"raw": value}
    derivation = projected.derivations[0]
    assert derivation.conversion == mode
    assert json.loads(derivation.source_value_json) == value
    assert json.loads(derivation.output_value_json) == expected


@pytest.mark.parametrize(
    "mode,value",
    [
        ("date_iso", "2025-02-29"),
        ("date_dmy", "29/02/1900"),
        ("date_mdy", "02/30/2024"),
        ("date_iso", "0000-01-01"),
        ("date_iso", "2025-13-01"),
        ("date_iso", "2025-01-00"),
        ("date_dmy", "31/04/2025"),
        ("date_mdy", "13/01/2025"),
        ("date_iso", "2025-2-03"),
        ("date_dmy", "1/02/2025"),
        ("date_mdy", "02/1/2025"),
        ("date_iso", " 2025-01-01"),
        ("date_iso", "2025-01-01 "),
        ("date_iso", "2025-01-01T00:00:00Z"),
        ("date_iso", "\uff12\uff10\uff12\uff15-\uff10\uff11-\uff10\uff11"),
        ("date_iso", 20250101),
        ("date_dmy", True),
        ("date_mdy", ["01/01/2025"]),
        ("date_iso", {}),
        ("date_iso", "01/02/2025"),
        ("date_dmy", "2025-02-01"),
        ("date_mdy", "2025-02-01"),
    ],
)
def test_invalid_dates_are_explicit_failures(mode, value):
    with pytest.raises(ProjectionError, match="Date conversion"):
        convert(value, mode)


def test_no_implicit_date_conversion_or_unknown_mode():
    assert convert("03/04/2025", "identity")[1].values == {"date": "03/04/2025"}
    assert convert("03/04/2025", "string")[1].values == {"date": "03/04/2025"}
    with pytest.raises(ValidationError):
        convert("03/04/2025", "date_auto")
