# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Typed keys, finite arithmetic, optional-column union and stable total ordering."""

import copy
import json

import pytest
from verboisy.product import SortKey, finite_aggregate, transform_rows
from verboisy.utils.exceptions import VerboisyError


def test_typed_keys_and_presence_are_distinct():
    rows = [
        {"id": str(i), "k": key, "count": i + 1} for i, key in enumerate([True, 1, 1.0, "1", None])
    ]
    rows.append({"id": "missing", "count": None, "later": 4})
    before = copy.deepcopy(rows)
    result = transform_rows(rows, schema_fields=["k", "count", "later"], groupby="k")
    assert len(result.rows) == 6 and rows == before
    assert len({row["id"] for row in result.rows}) == 6
    assert result.rows[-1]["count"] is None and "k" not in result.rows[-1]
    assert result.rows[-1]["later"] == 4.0
    assert result.rows[0]["later"] is None
    assert (
        result.rows[0]["k"] is True
        and isinstance(result.rows[1]["k"], int)
        and not isinstance(result.rows[1]["k"], bool)
        and isinstance(result.rows[2]["k"], float)
    )
    json.dumps(result.rows, allow_nan=False)


def test_finite_average_exact_sum_and_no_observed_inputs():
    assert finite_aggregate([1e308, 1e308], "average") == 1e308
    assert finite_aggregate([10**400, 10**400], "sum") == 2 * 10**400
    assert finite_aggregate([None, None], "sum") is None
    with pytest.raises(VerboisyError):
        finite_aggregate([1e308, 1e308], "sum")
    with pytest.raises(VerboisyError):
        finite_aggregate([float("nan")], "average")


@pytest.mark.parametrize("key", [{}, [], float("inf"), object()])
def test_invalid_group_keys_fail_before_publication(key):
    with pytest.raises(VerboisyError):
        transform_rows([{"id": "a", "k": key}], schema_fields=["k"], groupby="k")


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_total_order_stable_ties_and_null_last(direction):
    values = [1, False, "b", "B", [], {}, None]
    rows = [{"id": str(i), "v": value} for i, value in enumerate(values)] + [{"id": "missing"}]
    result = transform_rows(rows, schema_fields=["v"], sort_keys=[SortKey("v", direction)])
    assert [r["id"] for r in result.rows][-2:] == ["6", "missing"]
    expected = (
        ["0", "1", "2", "3", "4", "5"] if direction == "asc" else ["5", "4", "2", "3", "1", "0"]
    )
    assert [r["id"] for r in result.rows][:-2] == expected


@pytest.mark.parametrize("values,operation", [([10**400, 1.0], "sum"), ([float("inf")], "sum")])
def test_unrepresentable_aggregates_are_rejected(values, operation):
    with pytest.raises(VerboisyError):
        finite_aggregate(values, operation)


@pytest.mark.parametrize("value", [float("inf"), [float("nan")], object()])
def test_invalid_order_values_raise_safe_errors(value):
    from verboisy.product import _sort_value

    with pytest.raises(VerboisyError):
        _sort_value(value)
