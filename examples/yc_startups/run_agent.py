"""
Example script directly importing and running the Verboisy Agent
to find YC startups.
"""

import asyncio
import json
from pathlib import Path
from pprint import pprint

from verboisy.core.agent import Agent
from verboisy.utils.config import settings

# Force console logging for the example
settings.log_level = "DEBUG"

async def main() -> None:
    schema_path = Path(__file__).parent / "schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        target_schema = json.load(f)

    goal = "Go to ycombinator.com/companies and extract the top 5 most recently launched AI startups."

    agent = Agent(goal=goal, target_schema=target_schema, max_steps=15)

    print(f"Starting Verboisy run for goal: {goal}")
    final_state = await agent.run()

    print("\n--- Run Complete ---")
    print(f"Status: {final_state.status}")
    print(f"Steps taken: {final_state.step_count}")
    print(f"Extracted Records: {len(final_state.extracted_data)}")

    if final_state.extracted_data:
        print("\nExtracted Data:")
        pprint(final_state.extracted_data)


if __name__ == "__main__":
    asyncio.run(main())
