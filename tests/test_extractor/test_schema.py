"""
Unit tests for dynamic Pydantic schema generation.
"""

import pytest
from pydantic import ValidationError
from verboisy.extractor.schema_builder import SchemaBuilder


def test_build_model_from_json_schema() -> None:
    json_schema = {
        "properties": {
            "title": {"type": "string"},
            "price": {"type": "number"},
            "in_stock": {"type": "boolean"},
        },
        "required": ["title", "price"],
    }

    dynamic_model = SchemaBuilder.build_model("Product", json_schema)

    # Valid data
    valid_data = {"title": "Laptop", "price": 999.99, "in_stock": True}
    obj = dynamic_model.model_validate(valid_data)
    assert obj.title == "Laptop"
    assert obj.price == 999.99

    # Missing optional data
    valid_data_missing_opt = {"title": "Phone", "price": 500.0}
    obj2 = dynamic_model.model_validate(valid_data_missing_opt)
    assert obj2.in_stock is None

    # Missing required data raises error
    invalid_data = {"title": "Monitor"}
    with pytest.raises(ValidationError):
        dynamic_model.model_validate(invalid_data)


def test_build_model_flat_schema() -> None:
    flat_schema = {"name": {"type": "string"}, "age": {"type": "integer"}}

    dynamic_model = SchemaBuilder.build_model("Person", flat_schema)

    obj = dynamic_model.model_validate({"name": "Alice", "age": 30})
    assert obj.name == "Alice"
    assert obj.age == 30
