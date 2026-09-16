"""
Dynamically creates Pydantic v2 models from standard JSON schemas.
"""

from typing import Any, cast

from pydantic import BaseModel, Field, create_model

from verboisy.utils.exceptions import ExtractionError
from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class SchemaBuilder:
    """Utility class to parse JSON schemas and return Pydantic models."""

    @classmethod
    def build_model(
        cls,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> type[BaseModel]:
        """
        Convert a simple JSON schema dict into a Pydantic Model class.

        Args:
            schema_name: The name to assign to the generated model.
            json_schema: A dictionary describing the target schema fields.
                         e.g., {"company_name": {"type": "string"}, "valuation": {"type": "integer"}}

        Returns:
            Type[BaseModel]: A dynamically generated Pydantic model class.
        """
        fields: dict[str, Any] = {}
        properties = json_schema.get("properties", {})
        required_fields = set(json_schema.get("required", []))

        if not properties:
            # Assume flat schema dictionary if 'properties' root is missing
            properties = json_schema

        for field_name, field_def in properties.items():
            field_type_str = field_def.get("type", "string")
            python_type = cls._map_json_type(field_type_str)

            is_required = field_name in required_fields

            if is_required:
                fields[field_name] = (
                    python_type,
                    Field(..., description=field_def.get("description", "")),
                )
            else:
                fields[field_name] = (
                    python_type | None,
                    Field(None, description=field_def.get("description", "")),
                )

        try:
            model = create_model(schema_name, **fields)
            return cast(type[BaseModel], model)
        except Exception as e:
            logger.error("Failed to build dynamic schema", schema_name=schema_name, error=str(e))
            raise ExtractionError(f"Failed to compile dynamic Pydantic model: {e}") from e

    @staticmethod
    def _map_json_type(json_type: str) -> type:
        """Map JSON types to Python types."""
        mapping: dict[str, type] = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return mapping.get(json_type.lower(), str)
