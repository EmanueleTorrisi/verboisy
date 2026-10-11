# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reference-year columns remain explicit, typed, same-row and replayable."""

import json
from dataclasses import FrozenInstanceError, asdict

import pytest
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.extractor.projection import ProjectionError
from verboisy.extractor.temporal_projection import project_reference_year


def row(value, year):
    return parse_dataset(json.dumps([{"value": value, "year": year}]).encode(), "json").rows[0]


@pytest.mark.parametrize("year", [1000, 2025, 9999, "1000", "2025", "9999"])
def test_explicit_years_keep_original_types_and_immutable_locations(year):
    source = row("002", year)
    before = source.values_json
    result = project_reference_year(source, "/value", "/year")
    assert (
        result.reference_year == int(year)
        and isinstance(result.reference_year, int)
        and not isinstance(result.reference_year, bool)
    )
    assert result.value == "002" and result.source_value_json == '"002"'
    assert json.loads(result.observed_year_json) == year
    assert result.value_pointer == "/value" and result.year_pointer == "/year"
    assert asdict(result)["policy_version"] == "1"
    assert source.values_json == before
    with pytest.raises(FrozenInstanceError):
        result.reference_year = 1900


@pytest.mark.parametrize("value", [None, True, 2, 2.5, "Anaïs 通常人口", {"x": [1, None]}])
def test_field_values_are_preserved_without_temporal_coercion(value):
    result = project_reference_year(row(value, "2025"), "/value", "/year")
    assert result.value == value
    if isinstance(value, dict):
        copied = result.value
        copied["x"].append(3)
        assert result.value == value


@pytest.mark.parametrize(
    "year",
    [
        None,
        True,
        False,
        2025.0,
        [],
        {},
        "",
        " 2025",
        "2025 ",
        "2025\n",
        "+2025",
        "02025",
        "025",
        "999",
        "10000",
        "2025.0",
        "2.025e3",
        "\uff12\uff10\uff12\uff15",
        "٢٠٢٥",
        "2025-01-01",
        "2024/25",
        "2024\u20132025",
        "FY2025",
        "as of 2025",
        "=2025",
        999,
        10000,
        -2025,
    ],
)
def test_missing_ambiguous_or_noninteger_years_fail(year):
    with pytest.raises(ProjectionError):
        project_reference_year(row(2, year), "/value", "/year")


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b'value,year\r\n"Ana\nis",2025\r\n'),
        ("json", b'[{"value":"Ana\\nis","year":2025}]'),
        ("jsonl", b'\n{"value":"Ana\\nis","year":"2025"}\n'),
    ],
)
def test_exact_bytes_physical_locations_and_repeated_derivation(fmt, body):
    dataset = parse_dataset(body, fmt)
    source = dataset.rows[0]
    result = project_reference_year(source, "/value", "/year")
    assert result == project_reference_year(source, "/value", "/year")
    assert (result.row_index, result.source_pointer, result.line_start, result.line_end) == (
        source.row_index,
        source.source_pointer,
        source.line_start,
        source.line_end,
    )
    assert result.value == "Ana\nis" and result.reference_year == 2025
    assert dataset.original_bytes == body


def test_nested_escaped_pointers_bind_only_the_selected_row():
    dataset = parse_dataset(
        b'[{"a/b":[{"~value":2,"year":2024}]},{"a/b":[{"~value":2,"year":2025}]}]',
        "json",
    )
    results = [
        project_reference_year(source, "/a~1b/0/~0value", "/a~1b/0/year") for source in dataset.rows
    ]
    assert [result.reference_year for result in results] == [2024, 2025]
    assert [result.row_index for result in results] == [1, 2]
    assert results[0].source_value_json == results[1].source_value_json == "2"
    assert results[0].observed_year_json != results[1].observed_year_json


@pytest.mark.parametrize(
    "value_pointer,year_pointer",
    [
        ("value", "/year"),
        ("/value", "year"),
        ("/bad~2", "/year"),
        ("/value", "/bad~2"),
        ("/missing", "/year"),
        ("/value", "/missing"),
        ("/" + "/".join(["x"] * 33), "/year"),
        ("/value", "/" + "/".join(["x"] * 33)),
    ],
)
def test_invalid_missing_and_deep_pointers_fail(value_pointer, year_pointer):
    with pytest.raises(ProjectionError):
        project_reference_year(row(2, 2025), value_pointer, year_pointer)


@pytest.mark.parametrize("field", ["published", "date", "year"])
def test_other_columns_cannot_supply_a_missing_declared_reference_year(field):
    source = parse_dataset(json.dumps([{"value": 2, field: "2025"}]).encode(), "json").rows[0]
    with pytest.raises(ProjectionError):
        project_reference_year(source, "/value", "/reference_year")


@pytest.mark.parametrize("value_json", ["Infinity", '"\\ud800"'])
def test_manual_nonfinite_and_invalid_utf8_values_cannot_emit_provenance(value_json):
    source = SourceRow(1, "/0", None, None, '{"value":' + value_json + ',"year":2025}')
    with pytest.raises(ProjectionError, match="finite UTF-8 JSON"):
        project_reference_year(source, "/value", "/year")
