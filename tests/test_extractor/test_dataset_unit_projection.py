# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared unit columns ground exact arithmetic and keep source row locators intact."""

import json
from dataclasses import FrozenInstanceError, asdict

import pytest
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.extractor.projection import ProjectionError
from verboisy.extractor.unit_projection import project_unit_value


def row(value, unit):
    return parse_dataset(json.dumps([{"amount": value, "unit": unit}]).encode(), "json").rows[0]


@pytest.mark.parametrize(
    "value,label,expected,base",
    [
        (2, "thousand persons", 2000, "person"),
        ("2", "thousand persons", 2000, "person"),
        ("2.5", "million people", 2500000, "person"),
        (0.002, "kg", 2, "gram"),
        ("0.0005", "kg", 0.5, "gram"),
        (-2, "kilometres", -2000, "meter"),
        (0, "g", 0, "gram"),
        (None, "people", None, "person"),
        (9007199254740993, "thousand persons", 9007199254740993000, "person"),
        ("9007199254740993", "thousand persons", 9007199254740993000, "person"),
        ("1e3", "grams", 1000, "gram"),
        ("-0.5", "  KG.  ", -500, "gram"),
    ],
)
def test_complete_grounded_units_and_exact_numeric_values(value, label, expected, base):
    source = row(value, label)
    before = source.values_json
    result = project_unit_value(source, "/amount", "/unit")
    assert result.value == expected and result.canonical_unit.base_unit == base
    assert result.canonical_unit.multiplier == 1
    assert result.observed_unit_label == label
    assert json.loads(result.source_value_json) == value
    assert result.value_pointer == "/amount" and result.unit_pointer == "/unit"
    assert source.values_json == before
    assert asdict(result)["policy_version"] == "1"
    with pytest.raises(FrozenInstanceError):
        result.normalized_value_json = "0"


@pytest.mark.parametrize(
    "value,label",
    [
        (2, "m"),
        (2, "unknown"),
        (2, "kg dry weight"),
        (2, "people per km"),
        (2, "USD"),
        (2, "EUR"),
        (2, "million"),
        (2, ""),
        (2, None),
        (2, 1000),
        (2, ["kg"]),
        (2, "g" * 513),
        (True, "kg"),
        ({"number": 2}, "kg"),
        ([2], "kg"),
        (" 2", "kg"),
        ("2,000", "kg"),
        ("02", "kg"),
        ("NaN", "kg"),
        ("Infinity", "kg"),
        ("1e999", "kg"),
        ("0.12345678901234567890", "kg"),
    ],
)
def test_unknown_units_and_invalid_numbers_fail_explicitly(value, label):
    with pytest.raises(ProjectionError):
        project_unit_value(row(value, label), "/amount", "/unit")


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b'amount,unit\r\n"2.5",kg\r\n'),
        ("json", b'[{"amount":2.5,"unit":"kg"}]'),
        ("jsonl", b'\n{"amount":2.5,"unit":"kg"}\n'),
    ],
)
def test_source_locations_and_repeated_derivation(fmt, body):
    data = parse_dataset(body, fmt)
    source = data.rows[0]
    first = project_unit_value(source, "/amount", "/unit")
    second = project_unit_value(source, "/amount", "/unit")
    assert first == second and first.value == 2500
    assert (first.row_index, first.source_pointer, first.line_start, first.line_end) == (
        source.row_index,
        source.source_pointer,
        source.line_start,
        source.line_end,
    )
    assert data.original_bytes == body


def test_nested_and_escaped_pointers_keep_unit_and_value_in_same_row():
    data = parse_dataset(b'[{"a/b":[{"~value":2,"label":"kg"}]}]', "json")
    assert project_unit_value(data.rows[0], "/a~1b/0/~0value", "/a~1b/0/label").value == 2000


@pytest.mark.parametrize(
    "value_pointer,unit_pointer",
    [
        ("amount", "/unit"),
        ("/bad~2", "/unit"),
        ("/missing", "/unit"),
        ("/amount", "/missing"),
        ("/" + "/".join(["x"] * 33), "/unit"),
        ("/amount", "/" + "/".join(["x"] * 33)),
    ],
)
def test_invalid_or_missing_pointers_fail(value_pointer, unit_pointer):
    with pytest.raises(ProjectionError):
        project_unit_value(row(2, "kg"), value_pointer, unit_pointer)


def test_changed_unit_produces_new_derivation_from_raw_value():
    assert project_unit_value(row(2, "kg"), "/amount", "/unit").value == 2000
    assert project_unit_value(row(2, "grams"), "/amount", "/unit").value == 2


def test_nonfinite_manual_row_is_rejected():
    source = SourceRow(1, "/0", None, None, '{"amount":Infinity,"unit":"kg"}')
    with pytest.raises(ProjectionError, match="finite"):
        project_unit_value(source, "/amount", "/unit")


def test_rounded_scaling_is_rejected():
    with pytest.raises(ProjectionError, match="precision"):
        project_unit_value(row(0.00030000000000000003, "kg"), "/amount", "/unit")


def test_large_finite_value_scales_to_an_exact_integer():
    result = project_unit_value(row(1e308, "kg"), "/amount", "/unit")
    assert result.value == 10**311
    assert isinstance(result.value, int)


def test_nonfinite_normalizer_result_cannot_enter_derivation():
    from unittest.mock import patch

    with (
        patch("verboisy.extractor.unit_projection.normalize_unit_value", return_value=float("inf")),
        pytest.raises(ProjectionError, match="finite"),
    ):
        project_unit_value(row(2.5, "kg"), "/amount", "/unit")
