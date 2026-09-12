"""
Data extraction engine leveraging the LLM and dynamically generated schemas.
"""

from typing import Any, Dict, List, Type
from pydantic import BaseModel

from verboisy.utils.logger import get_logger
from verboisy.utils.exceptions import ExtractionError
from verboisy.llm.client import LLMClient
from verboisy.llm.prompts import EXTRACTION_PROMPT
from verboisy.browser.dom_parser import DOMParser
from verboisy.extractor.schema_builder import SchemaBuilder

logger = get_logger(__name__)


class ExtractionEngine:
    """Extracts structured JSON from HTML utilizing a target schema."""

    def __init__(self, target_schema: Dict[str, Any]) -> None:
        self.target_schema = target_schema
        self.model_class = SchemaBuilder.build_model("ExtractionTarget", target_schema)
        self.llm = LLMClient()

    async def extract_from_html(self, html_content: str) -> List[Dict[str, Any]]:
        """
        Analyze cleaned HTML and extract all instances matching the schema.

        Args:
            html_content: The raw HTML to parse.

        Returns:
            List[Dict[str, Any]]: A list of extracted items as dictionaries.
        """
        logger.info("Starting extraction process on page content")
        cleaned_html = DOMParser.clean_html(html_content)

        # Instruct the LLM on the target JSON structure
        schema_json_str = self.model_class.model_json_schema()

        user_prompt = f"""
        TARGET SCHEMA (JSON Schema format):
        {schema_json_str}

        HTML CONTENT TO ANALYZE:
        {cleaned_html[:20000]}  # Truncated to avoid context overflow on massive pages

        Extract ALL instances that match the target schema from the HTML above.
        Return the result as a JSON object containing a key 'results' which is an array of the extracted objects.
        """

        try:
            response = await self.llm.complete_json(EXTRACTION_PROMPT, user_prompt)
            results_array = response.get("results", [])

            validated_results = []
            for item in results_array:
                # Validate against the dynamic Pydantic model
                validated_item = self.model_class.model_validate(item)
                validated_results.append(validated_item.model_dump())

            logger.info("Extraction complete", extracted_count=len(validated_results))
            return validated_results

        except Exception as e:
            logger.error("Extraction failed", error=str(e))
            raise ExtractionError(f"Failed to extract structured data: {e}")
