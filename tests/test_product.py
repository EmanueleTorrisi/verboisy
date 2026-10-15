# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from verboisy.product import (
    SortKey,
    SourcePolicy,
    apply_smart_ids,
    infer_json_type,
    load_rows,
    parse_simple_schema,
    relation_field,
    transform_rows,
)
from verboisy.utils.exceptions import VerboisyError


def test_simple_schema_infers_common_types_and_nullable_fields():
    schema = parse_simple_schema("[age,name,birthdate,price,website,active]")
    properties = schema["items"]["properties"]
    assert properties["age"] == {"type": ["integer", "null"]}
    assert properties["name"] == {"type": ["string", "null"]}
    assert properties["birthdate"]["format"] == "date"
    assert properties["price"] == {"type": ["number", "null"]}
    assert properties["website"]["format"] == "uri"
    assert properties["active"] == {"type": ["boolean", "null"]}
    assert schema["items"]["required"] == [
        "age",
        "name",
        "birthdate",
        "price",
        "website",
        "active",
    ]


def test_simple_schema_string_mode_and_validation():
    schema = parse_simple_schema(["name", "price"], strings=True)
    assert schema["items"]["properties"] == {
        "name": {"type": ["string", "null"]},
        "price": {"type": ["string", "null"]},
    }
    with pytest.raises(VerboisyError, match="generated automatically"):
        parse_simple_schema("[id,name]")
    with pytest.raises(VerboisyError, match="unique"):
        parse_simple_schema("[name,name]")


def test_inference_can_use_observed_values():
    assert infer_json_type("mystery", [1, 2]) == {"type": ["integer", "null"]}
    assert infer_json_type("mystery", [1.2, 2]) == {"type": ["number", "null"]}
    assert infer_json_type("mystery", [True, False]) == {"type": ["boolean", "null"]}


def test_source_policy_precedence_and_subdomains():
    policy = SourcePolicy(("example.com",), ("ads.example.com",), True)
    assert policy.permits("https://shop.example.com/item")
    assert not policy.permits("https://ads.example.com/item")
    assert not policy.permits("https://other.test/item")
    with pytest.raises(VerboisyError, match="requires"):
        SourcePolicy((), (), True)
    overlap = SourcePolicy(("example.com",), ("example.com",), False)
    assert not overlap.permits("https://example.com/item")


def test_ordering_preserves_mixed_priority_and_nulls_last():
    rows = [
        {"id": "a", "age": 20, "height": 180, "name": "B"},
        {"id": "b", "age": 20, "height": 190, "name": "C"},
        {"id": "c", "age": 19, "height": None, "name": "A"},
        {"id": "d", "age": 20, "height": 190, "name": "A"},
    ]
    result = transform_rows(
        rows,
        schema_fields=["age", "height", "name"],
        sort_keys=[
            SortKey("age", "asc"),
            SortKey("height", "desc"),
            SortKey("name", "asc"),
        ],
    )
    assert [row["id"] for row in result.rows] == ["c", "d", "b", "a"]


def test_grouping_drops_nonaggregable_fields_and_sorts_grouped_result():
    rows = [
        {"id": "1", "company": "A", "country": "IT", "revenue": 5, "employees": 2},
        {"id": "2", "company": "B", "country": "IT", "revenue": 7, "employees": 3},
        {"id": "3", "company": "C", "country": "DE", "revenue": 20, "employees": 1},
    ]
    result = transform_rows(
        rows,
        schema_fields=["company", "country", "revenue", "employees"],
        groupby="country",
        sort_keys=[SortKey("company"), SortKey("revenue", "desc")],
    )
    assert [row["country"] for row in result.rows] == ["DE", "IT"]
    assert result.rows[1]["revenue"] == 12
    assert result.rows[1]["employees"] == 5
    assert all(row["id"].startswith("group_") for row in result.rows)
    assert "company" in result.group_plan.removed_fields
    assert "Ignored sort key: company" in result.notices


def test_smartid_exact_and_ambiguous_matching_is_conservative():
    old = [
        {"id": "p1", "name": "John", "surname": "Smith", "company": "Meta"},
        {"id": "p2", "name": "John", "surname": "Smith", "company": "Other"},
    ]
    linked, decisions = apply_smart_ids(
        [
            {"id": "n1", "name": "John", "surname": "Smith", "company": "Meta", "age": 42},
            {"id": "n2", "name": "John", "surname": "Smith", "age": 40},
        ],
        old,
        "person_id",
    )
    assert linked[0]["person_id"] == "p1"
    assert linked[1]["person_id"] is None
    assert decisions[0]["outcome"] == "exact"
    assert decisions[1]["outcome"] == "ambiguous"


def test_smartid_rejects_multiple_strong_matches():
    old = [
        {"id": "a", "website": "https://example.com"},
        {"id": "b", "website": "https://example.com"},
    ]
    linked, decisions = apply_smart_ids(
        [{"id": "n", "website": "https://example.com"}], old, "company_id"
    )
    assert linked[0]["company_id"] is None
    assert decisions[0]["outcome"] == "ambiguous"


def test_relation_name_is_semantic():
    assert relation_field("people.csv") == "person_id"
    assert relation_field("companies.json") == "company_id"
    assert relation_field("products.csv") == "product_id"


def test_load_rows_validates_ids_and_formats(tmp_path: Path):
    json_path = tmp_path / "people.json"
    json_path.write_text(json.dumps([{"id": "1", "name": "A"}]), encoding="utf-8")
    assert load_rows(json_path)[0]["name"] == "A"

    csv_path = tmp_path / "people.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "name"])
        writer.writeheader()
        writer.writerow({"id": "1", "name": "A"})
    assert load_rows(csv_path)[0]["id"] == 1

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"name": "A"}]), encoding="utf-8")
    with pytest.raises(VerboisyError, match="missing a row id"):
        load_rows(bad)


def test_domain_normalization_and_invalid_forms():
    assert SourcePolicy(("HTTPS://Example.COM/path",), (), False).include == ("example.com",)
    for value in ("", "bad/domain", "bad domain", "bad@domain", "a..b", "bad_underscore"):
        with pytest.raises(VerboisyError):
            SourcePolicy((value,), (), False)
    with pytest.raises(VerboisyError):
        SourcePolicy(("http://[bad",), (), False)
    assert not SourcePolicy().permits("http://[bad")


def test_additional_inference_paths():
    assert infer_json_type("created_at")["format"] == "date-time"
    assert infer_json_type("is_public") == {"type": ["boolean", "null"]}
    assert infer_json_type("item_count") == {"type": ["integer", "null"]}
    assert infer_json_type("product_url")["format"] == "uri"
    assert infer_json_type("mystery", ["2025-01-01", "2026-01-01"])["format"] == "date"
    assert infer_json_type("mystery", ["x", "y"]) == {"type": ["string", "null"]}
    assert infer_json_type("price", [object()]) == {"type": ["number", "null"]}


def test_simple_schema_rejects_malformed_and_empty():
    with pytest.raises(VerboisyError, match="look like"):
        parse_simple_schema("name,price")
    with pytest.raises(VerboisyError, match="at least one"):
        parse_simple_schema("[]")
    with pytest.raises(VerboisyError, match="at least one"):
        parse_simple_schema(["name", ""])


def test_load_rows_rejects_untrusted_inputs(tmp_path: Path):
    missing = tmp_path / "missing.json"
    with pytest.raises(VerboisyError, match="Cannot read"):
        load_rows(missing)

    too_large = tmp_path / "large.json"
    too_large.write_text("[]", encoding="utf-8")
    with pytest.raises(VerboisyError, match="exceeds"):
        load_rows(too_large, max_bytes=1)

    wrong_shape = tmp_path / "shape.json"
    wrong_shape.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(VerboisyError, match="array of objects"):
        load_rows(wrong_shape)

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(VerboisyError, match="JSON"):
        load_rows(invalid_json)

    unsupported = tmp_path / "data.txt"
    unsupported.write_text("x", encoding="utf-8")
    with pytest.raises(VerboisyError, match="CSV or JSON"):
        load_rows(unsupported)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps([{"id": "x"}, {"id": "x"}]), encoding="utf-8")
    with pytest.raises(VerboisyError, match="duplicate ids"):
        load_rows(duplicate)

    invalid_utf = tmp_path / "invalid_utf.json"
    invalid_utf.write_bytes(b"\xff\xfe")
    with pytest.raises(VerboisyError, match="UTF-8"):
        load_rows(invalid_utf)


def test_load_rows_rejects_bad_csv_headers(tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(VerboisyError, match="header"):
        load_rows(empty)

    duplicate = tmp_path / "dup.csv"
    duplicate.write_text("id,id\na,b\n", encoding="utf-8")
    with pytest.raises(VerboisyError, match="duplicate column"):
        load_rows(duplicate)


def test_relation_field_plural_and_fallback_rules():
    assert relation_field("universities.csv") == "university_id"
    assert relation_field("products.csv") == "product_id"
    assert relation_field("children.csv") == "child_id"
    assert relation_field("classes.csv") == "class_id"
    assert relation_field("!!!.csv") == "entity_id"


def test_smartid_identity_edge_cases():
    previous = [{"id": "p", "sku": 123, "name": "A", "city": "Rome"}]
    linked, decisions = apply_smart_ids(
        [
            {"id": "n1", "sku": 123},
            {"id": "n2", "name": "A", "city": "Milan"},
            {"id": "n3", "name": "A"},
            {"id": "n4", "sku": ""},
        ],
        previous,
        "product_id",
    )
    assert linked[0]["product_id"] == "p"
    assert decisions[0]["matched_fields"] == ["sku"]
    assert all(row["product_id"] is None for row in linked[1:])


def test_string_normalization_preserves_extras_and_types():
    rows = [
        {
            "id": "1",
            "flag": True,
            "meta": {"b": 2, "a": 1},
            "count": 3,
            "missing": None,
            "extra": "keep",
        }
    ]
    result = transform_rows(
        rows,
        schema_fields=["flag", "meta", "count", "missing"],
        strings=True,
    )
    row = result.rows[0]
    assert row["flag"] == "true"
    assert row["meta"] == '{"a": 1, "b": 2}'
    assert row["count"] == "3"
    assert row["missing"] is None
    assert row["extra"] == "keep"


def test_grouping_edge_cases_and_sort_value_types():
    with pytest.raises(VerboisyError, match="unknown field"):
        transform_rows([{"id": "1", "country": "IT"}], schema_fields=["country"], groupby="city")

    rows = [
        {"id": "1", "country": "IT", "price": 10.0, "score": None, "flag": True},
        {"id": "2", "country": "IT", "price": 20.0, "score": None, "flag": False},
    ]
    grouped = transform_rows(
        rows, schema_fields=["country", "price", "score", "flag"], groupby="country"
    )
    assert grouped.rows[0]["price"] == 15.0
    assert grouped.rows[0]["score"] is None
    assert "flag" in grouped.group_plan.removed_fields

    empty = transform_rows(
        [], schema_fields=["country"], groupby="country", sort_keys=[SortKey("country")]
    )
    assert empty.rows == [] and empty.applied_sort == [SortKey("country")]

    from datetime import datetime

    mixed = transform_rows(
        [
            {"id": "1", "value": True},
            {"id": "2", "value": False},
        ],
        schema_fields=["value"],
        sort_keys=[SortKey("value", "desc")],
    )
    assert mixed.rows[0]["value"] is True
    dated = transform_rows(
        [
            {"id": "1", "value": datetime(2025, 1, 1)},
            {"id": "2", "value": datetime(2026, 1, 1)},
        ],
        schema_fields=["value"],
        sort_keys=[SortKey("value")],
    )
    assert dated.rows[0]["id"] == "1"


def test_sort_key_rejects_invalid_values():
    with pytest.raises(VerboisyError, match="field"):
        SortKey("  ")
    with pytest.raises(VerboisyError, match="direction"):
        SortKey("age", "sideways")  # type: ignore[arg-type]


def test_grouping_preserves_null_when_one_group_has_no_numeric_values():
    rows = [
        {"id": "1", "country": "IT", "price": 10.0},
        {"id": "2", "country": "DE", "price": None},
    ]

    result = transform_rows(
        rows,
        schema_fields=["country", "price"],
        groupby="country",
    )

    by_country = {row["country"]: row for row in result.rows}

    assert by_country["IT"]["price"] == 10.0
    assert by_country["DE"]["price"] is None


@pytest.mark.parametrize(
    "bad_id",
    [
        0,
        -1,
    ],
)
def test_load_rows_rejects_nonpositive_integer_ids(
    tmp_path,
    bad_id,
):
    import json

    from verboisy.product import load_rows
    from verboisy.utils.exceptions import VerboisyError

    path = tmp_path / "bad-id.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": bad_id,
                    "name": "A",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        VerboisyError,
        match="invalid row id",
    ):
        load_rows(path)


@pytest.mark.parametrize(
    "bad_id",
    [
        1.5,
        [],
        {},
    ],
)
def test_load_rows_rejects_invalid_id_types(
    tmp_path,
    bad_id,
):
    import json

    from verboisy.product import load_rows
    from verboisy.utils.exceptions import VerboisyError

    path = tmp_path / "bad-type.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": bad_id,
                    "name": "A",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        VerboisyError,
        match="missing a row id",
    ):
        load_rows(path)


def test_load_rows_accepts_positive_integer_id(
    tmp_path,
):
    import json

    from verboisy.product import load_rows

    path = tmp_path / "integer-id.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "name": "A",
                }
            ]
        ),
        encoding="utf-8",
    )

    rows = load_rows(path)

    assert rows == [
        {
            "id": 1,
            "name": "A",
        }
    ]
