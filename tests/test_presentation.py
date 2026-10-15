# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Formatting preserves source values, ambiguity and complete measurement intervals."""

import copy

import pytest
from verboisy.presentation import (
    PresentationPreferences,
    field_schema,
    preferences,
    present_rows,
    present_value,
)
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize(
    "value,field,options,expected",
    [
        ("100 lb", {}, {}, "45.359237 kg"),
        ("100 - 120 lbs", {}, {}, "45.359237 - 54.431084 kg"),
        ("100 lbs - 120 pounds", {}, {}, "45.359237 - 54.431084 kg"),
        ("45 - 55 kg", {}, {}, "45 - 55 kg"),
        ("1 kilograms", {}, {"mass_unit": "lb"}, "2.204623 lb"),
        ("1,000 grams", {}, {}, "1 kg"),
        ("6 feet", {}, {}, "1.8288 m"),
        ("100 cm", {}, {"length_unit": "ft"}, "3.28084 ft"),
        ("1000 mm", {}, {}, "1 m"),
        ("1 inch", {}, {}, "0.0254 m"),
        ("1 m", {"x-verboisy-dimension": "length"}, {"length_unit": "ft"}, "3.28084 ft"),
        ("1 in", {"x-verboisy-dimension": "length"}, {}, "0.0254 m"),
        ("-0.0000001 grams", {}, {}, "0 kg"),
        ("1 to 2 pounds", {}, {}, "0.453592 - 0.907185 kg"),
        ("2026-10-08", {"format": "date"}, {}, "08/10/2026"),
        ("0001-01-02", {"format": "date"}, {}, "02/01/0001"),
        ("2026-10-08", {"format": "date"}, {"date_format": "mdy"}, "10/08/2026"),
        (
            "2026-10-08T12:34:56.123+02:00",
            {"format": "date-time"},
            {},
            "08/10/2026 12:34:56.123+02:00",
        ),
    ],
)
def test_explicit_measurements_and_iso_dates(value, field, options, expected):
    assert present_value(value, field, preferences(options)) == expected


@pytest.mark.parametrize(
    "value,field,options",
    [
        (100, {}, {}),
        (None, {}, {}),
        (True, {}, {}),
        ("x" * 201, {}, {}),
        ("over 100 lb", {}, {}),
        ("100 lbs", {}, {"mass_unit": "source"}),
        ("6 feet", {}, {"length_unit": "source"}),
        ("100 - 50 lb", {}, {}),
        ("100 - 100 lb", {}, {}),
        ("100 kg - 120 lb", {}, {}),
        ("1 stone", {}, {}),
        ("1m", {}, {}),
        ("1 in", {}, {}),
        ("plain text", {}, {}),
        ("9" * 100 + " lb", {}, {}),
        ("08/10/2026", {"format": "date"}, {}),
        ("2026-02-30", {"format": "date"}, {}),
        ("2026-10-08", {"format": "date"}, {"date_format": "iso"}),
        ("2026-10-08", {"format": "date"}, {"date_format": "source"}),
        ("2026-10-08T12:34:56", {"format": "date-time"}, {}),
        ("2026-13-08T12:34:56Z", {"format": "date-time"}, {}),
        ("100 lb", {"format": "uri"}, {}),
    ],
)
def test_missing_context_or_ambiguous_values_unchanged(value, field, options):
    assert present_value(value, field, preferences(options)) == value


@pytest.mark.parametrize(
    "options",
    [{"mass_unit": "stone"}, {"date_format": "guess"}, {"length_unit": "kg"}, {"extra": True}],
)
def test_preferences_validate(options):
    with pytest.raises(VerboisyError, match="Display preferences"):
        preferences(options)


def test_nested_rows_and_identity_fields_do_not_mutate_input():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "a/b": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"d": {"type": "string", "format": "date"}},
                    },
                },
                "identifier": {"type": "string"},
            },
        },
    }
    rows = [{"id": "100 lb", "identifier": "100 lb", "a/b": [{"d": "2026-10-08"}]}]
    before = copy.deepcopy(rows)
    result = present_rows(rows, schema, PresentationPreferences(), protected=["/identifier"])
    assert result[0]["a/b"][0]["d"] == "08/10/2026"
    assert result[0]["id"] == result[0]["identifier"] == "100 lb"
    assert rows == before
    assert field_schema({"properties": {"x": False}}, "/x/y") == {}
    assert field_schema({"properties": {"x": False}}, "/x") == {}


def test_referenced_date_and_dimension_match_inline_presentation():
    from verboisy.presentation import present_rows
    from verboisy.presentation_config import PresentationPreferences

    schema = {
        "type": "object",
        "$defs": {
            "day": {"type": "string", "format": "date"},
            "length": {"type": "string", "x-verboisy-dimension": "length"},
        },
        "properties": {"day": {"$ref": "#/$defs/day"}, "length": {"$ref": "#/$defs/length"}},
    }
    rows = [{"id": 1, "day": "2026-10-08", "length": "2 m"}]
    formatted = present_rows(
        rows, schema, PresentationPreferences(date_format="dmy", length_unit="ft"), protected=[]
    )
    assert formatted[0]["day"] == "08/10/2026" and formatted[0]["length"] == "6.56168 ft"
    assert rows[0]["day"] == "2026-10-08"
    protected = present_rows(
        rows, schema, PresentationPreferences(date_format="dmy"), protected=["/day"]
    )
    assert protected[0]["day"] == "2026-10-08"
