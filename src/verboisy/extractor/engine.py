"""Extract candidates, validate each, and yield rows for immediate commit."""

import json
from collections.abc import AsyncIterator
from typing import Any

from verboisy.browser.dom_parser import DOMParser
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.llm.client import LLMClient
from verboisy.llm.prompts import EXTRACTION_PROMPT
from verboisy.utils.config import Settings, settings
from verboisy.utils.exceptions import BudgetExceededError, ExtractionError, LLMError


class ExtractionEngine:
    def __init__(
        self,
        target_schema: dict[str, Any],
        llm: LLMClient | None = None,
        config: Settings | None = None,
    ) -> None:
        self.config = config or settings
        self.target_schema = SchemaBuilder.normalize(target_schema)
        self.model_class = SchemaBuilder.build_model("ExtractionTarget", self.target_schema)
        self.llm = llm or LLMClient(config=self.config)

    async def iter_from_html(
        self, html_content: str, goal: str = ""
    ) -> AsyncIterator[dict[str, Any]]:
        cleaned = DOMParser.clean_html(html_content)
        prompt = json.dumps(
            {
                "goal": goal,
                "schema": self.target_schema,
                "html": cleaned[: self.config.max_dom_chars],
                "html_truncated": len(cleaned) > self.config.max_dom_chars,
                "response": {
                    "results": "array of records supported by the page and matching the goal"
                },
            },
            ensure_ascii=False,
        )
        try:
            response = await self.llm.complete_json(EXTRACTION_PROMPT, prompt)
            candidates = response.get("results")
            if not isinstance(candidates, list):
                raise ExtractionError("Extraction response must contain a results array")
            for index, candidate in enumerate(candidates):
                try:
                    record = self.model_class.model_validate(candidate)
                except Exception:
                    raise ExtractionError(
                        f"Record {index + 1} failed JSON Schema validation"
                    ) from None
                yield record.model_dump(by_alias=True, exclude_unset=True)
        except (ExtractionError, BudgetExceededError):
            raise
        except LLMError as exc:
            raise ExtractionError(
                f"Extraction model call failed: {exc}", details=exc.details
            ) from None
        except Exception as exc:
            raise ExtractionError(
                f"Failed to extract structured data ({type(exc).__name__})"
            ) from None

    async def extract_from_html(self, html_content: str, goal: str = "") -> list[dict[str, Any]]:
        return [record async for record in self.iter_from_html(html_content, goal)]

    def validate_collection(self, records: list[dict[str, Any]]) -> None:
        try:
            if self.target_schema["type"] == "array":
                SchemaBuilder.validator(self.target_schema).validate(records)
            else:
                for record in records:
                    self.model_class.model_validate(record)
        except Exception:
            raise ExtractionError("Saved collection does not satisfy the target schema") from None
