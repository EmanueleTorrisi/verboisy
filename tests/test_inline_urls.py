# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit URLs retain their paths and do not trigger unnecessary discovery."""

from unittest.mock import AsyncMock, patch

import pytest
from verboisy import api
from verboisy.evidence.models import TaskSpec
from verboisy.product import SourcePolicy
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("Read https://example.com/stats", ["https://example.com/stats"]),
        ("Read https://example.com/data please collect rows", ["https://example.com/data"]),
        ("Read http://example.com/stats", ["http://example.com/stats"]),
        (
            "Read https://example.com/data?series=population",
            ["https://example.com/data?series=population"],
        ),
        ("Read (https://example.com/stats).", ["https://example.com/stats"]),
        ("Read [statistics](https://example.com/stats).", ["https://example.com/stats"]),
        (
            "Read https://example.com/wiki/Topic_(statistics).",
            ["https://example.com/wiki/Topic_(statistics)"],
        ),
        (
            "Read (https://example.com/wiki/Topic_(statistics)).",
            ["https://example.com/wiki/Topic_(statistics)"],
        ),
        ("Read `https://example.com/stats`", ["https://example.com/stats"]),
        ('Read "https://example.com/stats"', ["https://example.com/stats"]),
        ("Read 'https://example.com/stats'", ["https://example.com/stats"]),
        ("Read <https://example.com/stats>", ["https://example.com/stats"]),
        ("Read https://example.com/stats\nthen collect rows", ["https://example.com/stats"]),
        ("Read HTTPS://EXAMPLE.COM/stats", ["https://example.com/stats"]),
        ("Read https://example.com/data?q=[stats]", ["https://example.com/data?q=[stats]"]),
        (
            "Read [https://example.com/stats], {https://example.com/data};",
            ["https://example.com/stats", "https://example.com/data"],
        ),
        (
            "Read https://example.com/stats and https://example.com/stats",
            ["https://example.com/stats"],
        ),
        ("Read http://[::1]:8080/stats", ["http://[::1]:8080/stats"]),
        (
            "Read https://example.com/data?q=a%20b&series=stats",
            ["https://example.com/data?q=a%20b&series=stats"],
        ),
    ],
)
async def test_inline_url_discovery_without_search(goal, expected):
    spec = TaskSpec()
    config = Settings(_env_file=None, search_provider="disabled")
    search = AsyncMock(side_effect=AssertionError("Unexpected provider request"))
    with patch("verboisy.api.web_search", search):
        seeds, observations = await api._discover_seeds(
            goal, spec, SourcePolicy(), config, api.build_research_plan(SCHEMA, spec.target_records)
        )
    assert seeds == expected
    assert observations == []
    search.assert_not_awaited()


@pytest.mark.parametrize(
    "goal",
    [
        "No URL supplied",
        "Read https://user:password@example.com/stats",
        "Read http://[bad]/stats",
        "Read https://blocked.test/stats",
    ],
)
async def test_invalid_or_excluded_inline_urls_do_not_become_seeds(goal):
    spec = TaskSpec()
    config = Settings(_env_file=None, search_provider="disabled")
    search = AsyncMock(side_effect=SearchUnavailableError("Offline fixture"))
    with patch("verboisy.api.web_search", search), pytest.raises(SearchUnavailableError):
        await api._discover_seeds(
            goal,
            spec,
            SourcePolicy((), ("blocked.test",), False),
            config,
            api.build_research_plan(SCHEMA, spec.target_records),
        )
    search.assert_awaited_once()


async def test_explicit_task_and_inline_seeds_deduplicate_in_order():
    spec = TaskSpec(seed_urls=["https://example.com/stats"])
    with patch("verboisy.api.web_search", AsyncMock(side_effect=AssertionError("search"))):
        seeds, _ = await api._discover_seeds(
            "Use https://example.com/stats and https://example.com/data",
            spec,
            SourcePolicy(),
            Settings(_env_file=None, search_provider="disabled"),
            api.build_research_plan(SCHEMA, spec.target_records),
        )
    assert seeds == ["https://example.com/stats", "https://example.com/data"]
