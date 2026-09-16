"""
Example script to extract pricing data from an e-commerce catalog.
"""

import asyncio
import json
from pathlib import Path

from verboisy.core.agent import Agent
from verboisy.storage.exporters import DataExporter
from verboisy.utils.config import settings

settings.headless_browser = False  # Show browser for demonstration


async def main() -> None:
    schema_path = Path(__file__).parent / "schema.json"
    with schema_path.open(encoding="utf-8") as f:
        target_schema = json.load(f)

    goal = (
        "Navigate to https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops "
        "and extract the details of the first 3 laptops shown on the page."
    )

    agent = Agent(goal=goal, target_schema=target_schema, max_steps=5)

    print(f"Extracting e-commerce data...\nGoal: {goal}")
    final_state = await agent.run()

    if final_state.status == "COMPLETED" and final_state.extracted_data:
        export_path = Path(__file__).parent / "laptops_pricing.csv"
        DataExporter.export_csv(final_state.extracted_data, export_path)
        print(f"\nSuccessfully extracted {len(final_state.extracted_data)} products.")
        print(f"Data exported to {export_path}")
    else:
        print("\nFailed to extract data or run did not complete successfully.")


if __name__ == "__main__":
    asyncio.run(main())
