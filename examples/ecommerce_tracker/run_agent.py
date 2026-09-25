"""Live pricing example using the shared async public API."""

import asyncio
from pathlib import Path

from verboisy import arun


async def main() -> None:
    result = await arun(
        goal="Open https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops "
        "and extract the first three laptops shown, with only values supported by the page.",
        schema=Path(__file__).with_name("schema.json"),
        export=Path(__file__).with_name("laptops_pricing.csv"),
    )
    print(result.run_id, result.status, len(result.records))
    if not result.completed:
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
