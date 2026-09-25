"""JSON Schema is authoritative; Pydantic wraps validated record values."""

import copy
import json
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from referencing import Registry

from verboisy.utils.exceptions import ExtractionError


class SchemaBuilder:
    @staticmethod
    def normalize(schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict):
            raise ExtractionError("Schema must be a JSON object")
        result = copy.deepcopy(schema)
        if (
            result
            and not any(k in result for k in ("type", "properties", "$ref", "$schema"))
            and all(isinstance(v, dict) for v in result.values())
        ):
            result = {"type": "object", "properties": result}
        result.setdefault("type", "object")
        if result["type"] not in ("array", "object"):
            raise ExtractionError("Top-level schema must be an object or an array of objects")
        if result["type"] == "array":
            item = result.get("items")
            if not isinstance(item, dict) or item.get("type") != "object":
                raise ExtractionError("Array schema must have object items")
        dialect = result.get("$schema", "https://json-schema.org/draft/2020-12/schema")
        if (
            not isinstance(dialect, str)
            or dialect.rstrip("#") != "https://json-schema.org/draft/2020-12/schema"
        ):
            raise ExtractionError("Only JSON Schema draft 2020-12 is supported")

        def check_refs(value: Any) -> None:
            if not isinstance(value, dict):
                return
            for key in ("$ref", "$dynamicRef"):
                if key in value and (
                    not isinstance(value[key], str) or not value[key].startswith("#")
                ):
                    raise ExtractionError("Only local fragment schema references are supported")
            # Visit schema-bearing keywords, not arbitrary instance values in const/default.
            for key in (
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
            ):
                children = value.get(key, {})
                if isinstance(children, dict):
                    for child in children.values():
                        check_refs(child)
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                children = value.get(key, [])
                if isinstance(children, list):
                    for child in children:
                        check_refs(child)
            for key in (
                "items",
                "contains",
                "additionalProperties",
                "unevaluatedProperties",
                "unevaluatedItems",
                "propertyNames",
                "if",
                "then",
                "else",
                "not",
            ):
                check_refs(value.get(key))

        try:
            json.dumps(result, allow_nan=False)
            check_refs(result)
            Draft202012Validator.check_schema(result)
        except (SchemaError, TypeError, ValueError) as exc:
            raise ExtractionError("Invalid JSON Schema") from exc
        return result

    @classmethod
    def validator(cls, schema: dict[str, Any]) -> Draft202012Validator:
        return Draft202012Validator(
            cls.normalize(schema), format_checker=FormatChecker(), registry=Registry()
        )

    @classmethod
    def build_model(cls, schema_name: str, json_schema: dict[str, Any]) -> type[BaseModel]:
        schema = cls.normalize(json_schema)
        root_validator = cls.validator(schema)
        record_schema = schema["items"] if schema["type"] == "array" else schema
        validator = root_validator.evolve(schema=record_schema)

        class ValidatedRecord(BaseModel):
            model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

            @model_validator(mode="before")
            @classmethod
            def validate_schema(cls, value: Any) -> Any:
                try:
                    json.dumps(value, allow_nan=False)
                    validator.validate(value)
                except (ValidationError, TypeError, ValueError) as exc:
                    raise ValueError("Record does not satisfy the supplied JSON Schema") from exc
                return value

        fields: dict[str, Any] = {}
        required = record_schema.get("required", [])
        for index, (name, definition) in enumerate(record_schema.get("properties", {}).items()):
            internal = (
                name
                if name.isidentifier() and not hasattr(BaseModel, name) and not name.startswith("_")
                else f"field_{index}"
            )
            while internal in fields or (
                internal in record_schema.get("properties", {}) and internal != name
            ):
                internal += "_"
            fields[internal] = (
                Any,
                Field(
                    ... if name in required else None,
                    alias=name,
                    description=definition.get("description", "")
                    if isinstance(definition, dict)
                    else "",
                ),
            )
        try:
            return cast(
                type[BaseModel], create_model(schema_name, __base__=ValidatedRecord, **fields)
            )
        except Exception as exc:
            raise ExtractionError("Failed to compile dynamic Pydantic model") from exc
