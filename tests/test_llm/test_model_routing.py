# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provider-scoped selection is deterministic, budgeted, and never probes a model."""

import json
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner
from verboisy import run
from verboisy.cli.main import app
from verboisy.core import search
from verboisy.evidence.models import TaskSpec
from verboisy.llm import client as llm
from verboisy.llm.configuration import inspect_model_configuration
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import BudgetExceededError, LLMError, SearchUnavailableError


def candidate(model, **overrides):
    return {
        "model": model,
        "context_tokens": 65_536,
        "max_output_tokens": 4_096,
        "json_object": True,
        "input_price_microdollars_per_million": 200_000,
        "output_price_microdollars_per_million": 400_000,
        **overrides,
    }


def setup(provider="anthropic", *, models=None, token_allowances=None, **values):
    primary = (
        models
        if models is not None
        else [
            candidate(
                f"{provider}/small",
                context_tokens=16_384,
                input_price_microdollars_per_million=50_000,
            ),
            candidate(f"{provider}/wide"),
            candidate(
                f"{provider}/review",
                roles=["escalation"],
                input_price_microdollars_per_million=400_000,
            ),
        ]
    )
    options = {
        "llm_min_interval_seconds": 0,
        "llm_retries": 0,
        "llm_model_routing": {
            "provider": provider,
            "models": primary,
            "input_tokens_by_role": token_allowances or {},
        },
        **values,
    }
    return Settings(_env_file=None, **options)


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "bedrock", "ollama"])
async def test_roles_choose_fitting_models_and_use_only_the_bound_profile(provider, monkeypatch):
    prefix = f"{provider}/"
    route_key = "fixture-profile-secret"
    config = setup(
        provider,
        llm_provider_profiles={prefix: {"api_key": route_key, "api_base": "https://bound.test/v1"}},
        litellm_api_key="legacy-secret",
        litellm_api_base="https://unapproved.test/v1",
    )
    complete = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value": 1}'))],
            usage=SimpleNamespace(total_tokens=8),
        )
    )
    monkeypatch.setattr(llm, "_complete", complete)
    client = llm.LLMClient(config=config)
    assert client.model_for("semantic_plan") == prefix + "small"
    assert client.model_for("source_assessment") == client.model == prefix + "wide"
    assert client.model_for("escalation") == prefix + "review"
    report = inspect_model_configuration(config)
    assert report["model_routing"]["provider"] == provider
    plan = report["model_routing"]["roles"]["semantic_plan"]
    assert plan == {
        "model": prefix + "small",
        "selection": "least_estimated_cost",
        "planned_input_tokens": 8192,
        "output_tokens": 4096,
        "estimated_microdollars": 2048,
    }
    serialized = json.dumps(report)
    for sensitive in (route_key, "legacy-secret", "bound.test", "unapproved.test"):
        assert sensitive not in serialized
    complete.assert_not_awaited()
    # A later Settings edit cannot swap the credentials of a route already prepared.
    config.llm_provider_profiles.clear()
    value = await llm.complete_json_for_role(client, "source_assessment", "Plan.", "Check.")
    assert value == {"value": 1}
    call = complete.await_args.kwargs
    assert (call["model"], call["api_key"], call["api_base"]) == (
        prefix + "wide",
        route_key,
        "https://bound.test/v1",
    )
    assert client.reserved_tokens > 4096 and client.total_tokens == 8


def test_capability_and_output_limits_control_eligibility():
    names = ["gemini/prompt", "gemini/tiny-output", "gemini/wide"]
    models = [
        candidate(
            names[0],
            json_object=False,
            input_price_microdollars_per_million=0,
            output_price_microdollars_per_million=0,
        ),
        candidate(
            names[1],
            max_output_tokens=256,
            input_price_microdollars_per_million=0,
            output_price_microdollars_per_million=0,
        ),
        candidate(names[2]),
    ]
    assert llm.LLMClient(config=setup("gemini", models=models)).model == names[2]
    config = setup(
        "gemini",
        models=models,
        llm_provider_profiles={names[0]: {"response_mode": "prompt"}},
    )
    assert llm.LLMClient(config=config).model == names[0]
    assert (
        "response_format"
        not in llm.LLMClient(config=config).provider_for(names[0]).request_options()
    )


def test_ties_and_manual_override_are_stable():
    models = [candidate("gemini/b"), candidate("gemini/a")]
    cfg = setup("gemini", models=models, semantic_plan_model="gemini/b")
    client = llm.LLMClient(config=cfg)
    assert client.model == "gemini/a" and client.model_for("semantic_plan") == "gemini/b"
    assert client.model_for("escalation") == "gemini/a" and not client.has_routed_escalation()
    cfg = setup("gemini", models=models, litellm_model="gemini/b")
    assert llm.LLMClient(config=cfg).model == "gemini/b"
    assert (
        llm.LLMClient(model="gemini/b", config=setup("gemini", models=models)).model == "gemini/b"
    )


@pytest.mark.parametrize(
    ("models", "reason"),
    [
        ([candidate("openai/gpt-unapproved")], "selected provider"),
        ([candidate("gemini/duplicate")] * 2, "unique"),
        ([candidate("gemini//bad")], "selected provider"),
        ([candidate("gemini/https://host.test")], "selected provider"),
        ([candidate("gemini/infeasible", max_output_tokens=65_536)], "both input and output"),
    ],
)
def test_invalid_catalogs_fail_before_routing(models, reason):
    with pytest.raises(ValidationError, match=reason):
        setup("gemini", models=models)


def test_legacy_gateway_is_never_inherited_in_catalog_mode():
    options = {
        "litellm_api_key": "unrelated-gateway-key",
        "litellm_api_base": "https://unrelated.test/v1",
        "models": [candidate("gemini/allowed"), candidate("gemini/unapproved")],
    }
    with pytest.raises(LLMError, match="No approved model fits"):
        llm.LLMClient(config=setup("gemini", **options))
    cfg = setup(
        "gemini", **options, llm_provider_profiles={"gemini/allowed": {"api_key": "matching"}}
    )
    assert llm.LLMClient(config=cfg).model == "gemini/allowed"
    with pytest.raises(LLMError, match="explicit model is incompatible"):
        llm.LLMClient(
            config=setup(
                "gemini",
                **options,
                extraction_model="openai/other",
                llm_provider_profiles={"gemini/": {}},
            )
        )


async def test_unplanned_or_oversized_requests_never_reach_the_provider(monkeypatch):
    complete = AsyncMock()
    monkeypatch.setattr(llm, "_complete", complete)
    client = llm.LLMClient(config=setup())
    with pytest.raises(LLMError, match="outside the approved provider"):
        await client.complete_json("Read", "Query", model="openai/unapproved")
    with pytest.raises(LLMError, match="configured context"):
        await llm.complete_json_for_role(client, "semantic_plan", "Read", "x" * 20_000)
    assert client.reserved_tokens == 0
    complete.assert_not_awaited()


async def test_schema_escalation_is_approved_and_shares_request_budget(monkeypatch):
    bad = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not JSON"))])
    good = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
    )
    complete = AsyncMock(side_effect=[bad, good, bad])
    monkeypatch.setattr(llm, "_complete", complete)
    cfg = setup(token_allowances={"extraction": 4_096}, max_tokens=128)
    client = llm.LLMClient(config=cfg)
    log = Mock()
    client.on_escalation = log
    value = await llm.complete_validated_for_role(client, "extraction", "Read", "Query", dict)
    assert value == {"ok": True}
    assert [call.kwargs["model"] for call in complete.await_args_list] == [
        "anthropic/small",
        "anthropic/review",
    ]
    assert log.call_args.args[0]["reason"] == "invalid_model_response"
    spent = client.reserved_tokens // 2
    capped = llm.LLMClient(config=cfg.model_copy(update={"model_request_budget": spent}))
    with pytest.raises(BudgetExceededError):
        await llm.complete_validated_for_role(capped, "extraction", "Read", "Query", dict)
    assert complete.await_count == 3 and capped.reserved_tokens == spent


@pytest.mark.parametrize("code, expected", [(None, "rate limit"), ("insufficient_quota", "quota")])
async def test_other_provider_rate_limits_are_labelled_correctly(code, expected, monkeypatch):
    error = RuntimeError("private upstream message")
    error.status_code = 429
    error.code = code
    monkeypatch.setattr(llm, "_complete", AsyncMock(side_effect=error))
    with pytest.raises(LLMError, match=f"Model provider {expected}") as failure:
        await llm.LLMClient(config=setup()).complete_json("Read", "Query")
    assert "private" not in str(failure.value)


async def test_catalog_discovery_never_implicitly_uses_an_unrelated_model_key(monkeypatch):
    openai = AsyncMock(return_value="openai search")
    brave = AsyncMock(return_value="independent search")
    monkeypatch.setattr(search, "openai_search", openai)
    monkeypatch.setattr(search, "brave_search", brave)
    cfg = setup("gemini", openai_api_key="unrelated-search-key")
    with pytest.raises(SearchUnavailableError, match="web search provider explicitly"):
        await search.web_search("source", cfg)
    assert (
        await search.web_search(
            "source", cfg.model_copy(update={"brave_search_api_key": "brave-key"})
        )
        == "independent search"
    )
    openai.assert_not_awaited()
    assert (
        await search.web_search("source", cfg.model_copy(update={"search_provider": "openai"}))
        == "openai search"
    )
    openai.assert_awaited_once()


def test_catalog_preview_reports_incompatible_roles_without_transport(tmp_path, monkeypatch):
    config = setup("ollama")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_MODEL_ROUTING", config.llm_model_routing.model_dump_json())
    complete = AsyncMock(side_effect=AssertionError("unexpected provider call"))
    monkeypatch.setattr(llm, "_complete", complete)
    result = CliRunner().invoke(app, ["model-config"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["role_models"]["extraction"] == "ollama/wide"
    monkeypatch.setenv("EXTRACTION_MODEL", "openai/private-incompatible-model")
    refused = CliRunner().invoke(app, ["model-config"])
    assert refused.exit_code == 1 and "explicit model is incompatible" in refused.output
    assert "private-incompatible" not in refused.output
    complete.assert_not_awaited()
    assert not list(tmp_path.iterdir())


def test_provider_selection_is_recorded_in_the_research_run(tmp_path, monkeypatch):
    source = tmp_path / "catalog.jsonl"
    source.write_bytes(b'{"title":"Prepared"}\n')
    database = tmp_path / "research.db"
    config = setup(
        "gemini",
        sqlite_db_path=str(database),
        dataset_local_roots=[str(tmp_path)],
        llm_provider_profiles={"gemini/": {"api_key": "fixture-secret", "max_tokens": 128}},
    )
    no_calls = AsyncMock(side_effect=AssertionError("unexpected model request"))
    monkeypatch.setattr(llm, "_complete", no_calls)
    result = run(
        config=config,
        goal="Prepare the supplied records",
        schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
        task=TaskSpec(
            target_records=1, dataset_sources=[{"format": "jsonl", "url": source.as_uri()}]
        ),
    )
    assert result.completed
    with closing(ResearchStore(database)) as store:
        events = store.events(result.run_id, "run_config")
    audit = events[-1]["payload"]
    assert audit["model"] == "gemini/wide"
    assert audit["max_output_tokens"] == 128
    assert audit["model_routing"]["roles"]["semantic_plan"]["model"] == "gemini/small"
    assert "fixture-secret" not in json.dumps(events)
    no_calls.assert_not_awaited()
