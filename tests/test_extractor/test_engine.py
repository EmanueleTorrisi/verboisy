from unittest.mock import AsyncMock

import pytest
from verboisy.extractor.engine import ExtractionEngine
from verboisy.utils.exceptions import ExtractionError


@pytest.mark.asyncio
async def test_extract_from_html_returns_validated_results() -> None:
    target_schema = {
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }

    engine = ExtractionEngine(target_schema)

    engine.llm.complete_json = AsyncMock(
        return_value={
            "results": [
                {"name": "Alice", "age": 30},
                {"name": "Bob"},
            ]
        }
    )

    result = await engine.extract_from_html("<html><body><h1>Users</h1></body></html>")

    assert result == [
        {"name": "Alice", "age": 30},
        {"name": "Bob"},
    ]

    engine.llm.complete_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_from_html_returns_empty_list_when_no_results() -> None:
    engine = ExtractionEngine(
        {
            "properties": {
                "name": {"type": "string"},
            },
        }
    )

    engine.llm.complete_json = AsyncMock(return_value={"results": []})

    result = await engine.extract_from_html("<html><body>No users</body></html>")

    assert result == []


@pytest.mark.asyncio
async def test_extract_from_html_raises_extraction_error_on_llm_failure() -> None:
    engine = ExtractionEngine(
        {
            "properties": {
                "name": {"type": "string"},
            },
        }
    )

    engine.llm.complete_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    with pytest.raises(ExtractionError, match="Failed to extract structured data"):
        await engine.extract_from_html("<html><body>Users</body></html>")


@pytest.mark.asyncio
async def test_extract_from_html_raises_extraction_error_on_invalid_result() -> None:
    engine = ExtractionEngine(
        {
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
    )

    engine.llm.complete_json = AsyncMock(
        return_value={
            "results": [
                {"name": "Alice", "age": "not-an-integer"},
            ]
        }
    )

    with pytest.raises(ExtractionError, match="failed JSON Schema validation"):
        await engine.extract_from_html("<html><body>Invalid data</body></html>")


async def test_extraction_rejects_missing_results_array():
    """Reject model responses without a results array."""
    engine = ExtractionEngine(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
    )

    engine.llm.complete_json = AsyncMock(return_value={"message": "No results"})

    with pytest.raises(
        ExtractionError,
        match="Extraction response must contain a results array",
    ):
        await engine.extract_from_html("<html></html>")


def test_validate_object_collection():
    """Validate each saved record against an object schema."""
    engine = ExtractionEngine(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }
    )

    engine.validate_collection([])

    engine.validate_collection(
        [
            {"name": "Alice"},
            {"name": "Bob"},
        ]
    )

    with pytest.raises(
        ExtractionError,
        match="Saved collection does not satisfy the target schema",
    ):
        engine.validate_collection(
            [
                {"name": 123},
            ]
        )
