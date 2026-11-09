# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reject ambiguous schemas and verify that encoding never coerces values."""

import pytest
from verboisy.streaming.analytics_contract import Column, columns_for, typed_cell, validate_limits
from verboisy.streaming.contract import StreamError

INTEGER = {"name": "id", "type": "int64", "nullable": False}


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {"version": "1"},
        {"version": 1, "columns": [INTEGER]},
        {"version": "1", "columns": "id"},
        {"version": "1", "columns": []},
        {"version": "1", "columns": [INTEGER] * 129},
        {"version": "1", "columns": [None]},
        {"version": "1", "columns": [{"name": "id"}]},
        {"version": "1", "columns": [INTEGER, INTEGER]},
    ],
)
def test_parquet_requires_an_unambiguous_bounded_contract(schema):
    with pytest.raises(StreamError):
        columns_for("parquet", schema)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("name", 2),
        ("name", "\n"),
        ("name", ""),
        ("name", "é" * 65),
        ("type", []),
        ("type", "number"),
        ("nullable", 1),
    ],
)
def test_parquet_rejects_invalid_column_entries(key, value):
    with pytest.raises(StreamError, match="column|Column"):
        columns_for("parquet", {"version": "1", "columns": [{**INTEGER, key: value}]})


def test_format_contract_does_not_silently_ignore_columns():
    assert columns_for("jsonl", None) == ()
    schema = {"version": "1", "columns": [INTEGER]}
    assert columns_for("parquet", schema) == (Column("id", "int64", False),)
    with pytest.raises(StreamError, match="only used for Parquet"):
        columns_for("jsonl", schema)
    with pytest.raises(StreamError, match="jsonl or parquet"):
        columns_for("csv", None)


@pytest.mark.parametrize(
    ("rows", "size"),
    [(True, 1), (1.0, 1), (0, 1), (1_000_001, 1), (1, False), (1, 1.0), (1, 0)],
)
def test_export_ceilings_reject_nonintegral_or_invalid_limits(rows, size):
    with pytest.raises(StreamError, match="shard|limit"):
        validate_limits(rows, size)


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("bool", False, False),
        ("int64", -(2**63), -(2**63)),
        ("int64", 2**63 - 1, 2**63 - 1),
        ("float64", 1.25, 1.25),
        ("string", "001", "001"),
        ("json", {"z": 1, "a": [True, None]}, '{"a":[true,null],"z":1}'),
    ],
)
def test_explicit_physical_types_preserve_values(kind, value, expected):
    result = typed_cell(Column("reading", kind, True), value)
    assert result == expected
    assert isinstance(result, type(expected))
    assert typed_cell(Column("reading", kind, True), None) is None


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("int64", True),
        ("int64", 1.0),
        ("int64", 2**63),
        ("int64", -(2**63) - 1),
        ("float64", 1),
        ("string", 5),
        ("bool", 0),
        ("json", None),
    ],
)
def test_bad_or_out_of_range_values_are_not_coerced(kind, value):
    with pytest.raises(StreamError, match="reading"):
        typed_cell(Column("reading", kind, False), value)
