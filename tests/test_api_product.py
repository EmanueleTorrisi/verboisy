# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Focused tests for simplified product API orchestration."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import verboisy.api as api
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.evidence.models import TaskSpec
from verboisy.product import SortKey, SourcePolicy
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import SearchUnavailableError, VerboisyError

EXPLICIT = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


def test_schema_and_export_helper_variants(tmp_path: Path):
    schema, simple = api._schema(EXPLICIT)
    assert schema == EXPLICIT and not simple
    with pytest.raises(VerboisyError, match="simple column"):
        api._schema(EXPLICIT, strings=True)

    schema, simple = api._schema(["name", "price"])
    assert simple and "price" in schema["items"]["properties"]

    path = tmp_path / "schema.json"
    path.write_text('{"type":"object","properties":{"name":{"type":"string"}}}', encoding="utf-8")
    assert not api._schema(path)[1]
    with pytest.raises(VerboisyError, match="simple column"):
        api._schema(path, strings=True)

    assert api._schema("[name]")[1]
    with pytest.raises(VerboisyError, match="simple column"):
        api._schema(str(path), strings=True)

    db = str(tmp_path / "runs.db")
    output = tmp_path / "data.csv"
    assert api._export_path(output, db) == output.resolve()
    assert api._export_path(None, db) is None
    with pytest.raises(VerboisyError, match="Duplicate"):
        api._export_paths([output, output], db)


def test_sort_normalization_accepts_public_shapes():
    existing = SortKey("name")
    assert api._normalize_sort_keys([existing, ("age", "desc"), {"field": "price"}]) == [
        existing,
        SortKey("age", "desc"),
        SortKey("price", "asc"),
    ]
    with pytest.raises(VerboisyError, match="Invalid sort"):
        api._normalize_sort_keys(["name"])  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_discovery_explicit_search_provider_and_brave(monkeypatch, tmp_path: Path):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="disabled"
    )
    spec = TaskSpec(seed_urls=["https://seed.test/"])
    plan = api.build_research_plan(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
        },
        spec.target_records,
    )
    seeds, observations = await api._discover_seeds(
        "goal",
        spec,
        SourcePolicy(),
        config,
        plan,
    )
    assert seeds == ["https://seed.test/"] and observations == []

    # Include rules request discovery, but explicit seeds let non-Brave configurations
    # proceed safely.
    seeds, _ = await api._discover_seeds(
        "goal",
        spec,
        SourcePolicy(("seed.test",), (), False),
        config,
        plan,
    )
    assert seeds == ["https://seed.test/"]

    with pytest.raises(VerboisyError, match="Automatic source discovery"):
        await api._discover_seeds(
            "goal",
            TaskSpec(),
            SourcePolicy(),
            config,
            plan,
        )

    config.search_provider = "brave"
    observation = SearchObservation(
        provider="brave",
        query="goal",
        results=[
            SearchResult(title="A", url="https://allowed.test/a"),
            SearchResult(title="B", url="https://blocked.test/b"),
        ],
    )
    mock = AsyncMock(return_value=observation)
    monkeypatch.setattr(api, "web_search", mock)
    policy = SourcePolicy(("allowed.test",), ("blocked.test",), True)
    seeds, observations = await api._discover_seeds(
        "goal",
        TaskSpec(),
        policy,
        config,
        plan,
    )
    assert seeds == ["https://allowed.test/a"]
    assert observations[0]["results"][0]["url"] == "https://allowed.test/a"
    assert all("blocked.test" not in item["url"] for item in observations[0]["results"])


@pytest.mark.asyncio
async def test_discovery_search_failure_falls_back_only_to_existing_seed(
    monkeypatch, tmp_path: Path
):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="brave"
    )
    monkeypatch.setattr(
        api,
        "web_search",
        AsyncMock(side_effect=SearchUnavailableError("down")),
    )
    spec = TaskSpec(seed_urls=["https://seed.test/"])
    plan = api.build_research_plan(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
        },
        spec.target_records,
    )
    seeds, observations = await api._discover_seeds(
        "https://seed.test/",
        spec,
        SourcePolicy(
            ("seed.test",),
            (),
            False,
        ),
        config,
        plan,
    )
    assert seeds == ["https://seed.test/"] and observations == []
    with pytest.raises(SearchUnavailableError):
        await api._discover_seeds(
            "goal",
            TaskSpec(),
            SourcePolicy(),
            config,
            plan,
        )


class _CompletingRunner:
    def __init__(self, store, rid, _config):
        self.store = store
        self.rid = rid

    async def run(self, _steps):
        self.store.finish(self.rid, "COMPLETED", "target_met", 0, 0)


@pytest.mark.asyncio
async def test_arun_product_options_exports_proof_and_smartid(monkeypatch, tmp_path: Path):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="disabled"
    )
    monkeypatch.setattr(api, "ResearchRunner", _CompletingRunner)
    monkeypatch.setattr(
        api,
        "_discover_seeds",
        AsyncMock(
            return_value=(
                ["https://example.test/"],
                [
                    {
                        "provider": "brave",
                        "query": "fixture",
                        "results": [{"title": "Source", "url": "https://example.test/"}],
                    }
                ],
            )
        ),
    )
    old = tmp_path / "people.json"
    old.write_text('[{"id":"old","name":"A"}]', encoding="utf-8")

    def smart_ids(rows, _previous, _relation, *, identity_fields):
        assert identity_fields == []
        return rows, [{"outcome": "none"}]

    monkeypatch.setattr("verboisy.output.apply_smart_ids", smart_ids)

    result = await api.arun(
        goal="Find names",
        schema="[name]",
        export=[tmp_path / "out.csv", tmp_path / "out.json"],
        task={"seed_urls": ["https://example.test/"], "max_depth": 1},
        include=["example.test"],
        avoid=["ads.example.test"],
        onlyinclude=True,
        strings=True,
        maxrows=2,
        order=[("name", "asc")],
        groupby=None,
        smartid=old,
        proof=True,
        config=config,
    )
    assert result.completed
    assert len(result.export_paths) == 2 and len(result.manifest_paths) == 2
    assert result.proof_path and result.proof_path.exists()
    assert result.inferred_schema is not None


@pytest.mark.asyncio
async def test_arun_research_mode_and_validation_edges(monkeypatch, tmp_path: Path):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="disabled"
    )
    with pytest.raises(VerboisyError, match="maxrows"):
        await api.arun(goal="x", schema="[name]", research=True, maxrows=2, config=config)
    with pytest.raises(VerboisyError, match="positive"):
        await api.arun(goal="x", schema="[name]", maxrows=True, config=config)

    monkeypatch.setattr(api, "ResearchRunner", _CompletingRunner)
    monkeypatch.setattr(api, "_discover_seeds", AsyncMock(return_value=([], [])))
    with pytest.raises(VerboisyError, match="found no permitted"):
        await api.arun(goal="x", schema="[name]", research=True, config=config)

    monkeypatch.setattr(
        api, "_discover_seeds", AsyncMock(return_value=(["https://example.test/"], []))
    )
    result = await api.arun(goal="x", schema="[name]", research=True, config=config)
    assert result.completed


@pytest.mark.asyncio
async def test_arun_proof_requires_destination_and_target_schema_conflict(
    monkeypatch, tmp_path: Path
):
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "runs.db"), search_provider="disabled"
    )
    monkeypatch.setattr(api, "ResearchRunner", _CompletingRunner)
    monkeypatch.setattr(
        api, "_discover_seeds", AsyncMock(return_value=(["https://example.test/"], []))
    )
    with pytest.raises(VerboisyError, match="proof requires"):
        await api.arun(goal="x", schema="[name]", proof=True, config=config)

    limited = {
        "type": "array",
        "minItems": 1,
        "maxItems": 1,
        "items": EXPLICIT["items"],
    }
    with pytest.raises(VerboisyError, match="collection limits"):
        await api.arun(
            goal="x",
            schema=limited,
            task={"seed_urls": ["https://example.test/"], "target_records": 2},
            config=config,
        )


def test_bounded_seed_frontier_uses_planner_budget():
    plan = api.build_research_plan(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                    }
                },
            },
        },
        5,
    )

    active, deferred = plan.split_initial_sources(
        [
            "https://one.test/",
            "https://two.test/",
            "https://three.test/",
            "https://four.test/",
            "https://five.test/",
        ]
    )

    assert len(active) == 3
    assert active == [
        "https://one.test/",
        "https://two.test/",
        "https://three.test/",
    ]
    assert deferred == [
        "https://four.test/",
        "https://five.test/",
    ]


@pytest.mark.asyncio
async def test_bounded_run_persists_extra_seeds_as_deferred(
    monkeypatch,
    tmp_path,
):
    from unittest.mock import AsyncMock

    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore
    from verboisy.utils.config import Settings

    urls = [
        "https://one.test/",
        "https://two.test/",
        "https://three.test/",
        "https://four.test/",
        "https://five.test/",
    ]

    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "seed-frontier.db"),
        search_provider="disabled",
    )

    monkeypatch.setattr(
        api.ResearchRunner,
        "run",
        AsyncMock(
            return_value=("PAUSED", "test"),
        ),
    )

    result = await api.arun(
        goal="Find five names",
        schema=["name"],
        task=TaskSpec(
            seed_urls=urls,
        ),
        maxrows=5,
        config=config,
    )

    store = ResearchStore(config.sqlite_db_path)

    try:
        pages = {row["url"]: row["status"] for row in store.pages(result.run_id)}

        assert pages == {
            "https://one.test/": "queued",
            "https://two.test/": "queued",
            "https://three.test/": "queued",
            "https://four.test/": "deferred",
            "https://five.test/": "deferred",
        }

        events = store.events(
            result.run_id,
            "seed_frontier",
        )

        assert events[-1]["payload"] == {
            "discovered": 5,
            "active": 3,
            "deferred": 2,
        }

    finally:
        store.close()
