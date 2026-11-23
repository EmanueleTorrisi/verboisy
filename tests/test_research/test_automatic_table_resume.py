# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Prove automatic discovery, table extraction, and interrupted review cooperate."""

import json
from collections import Counter
from contextlib import closing
from types import SimpleNamespace

from verboisy import arun
from verboisy.core.search import SearchObservation, SearchResult
from verboisy.core.semantic_planner import SEMANTIC_PLANNER
from verboisy.core.source_assessment import SOURCE_ASSESSMENT_PROMPT
from verboisy.extractor.evidenced import PROPOSE, REVIEW
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

URL = "https://certification.example.test/registry"
HTML = (
    "<html><body><h1>Certificate registry</h1><table><thead><tr>"
    "<th>Equipment</th><th>Last Inspection</th><th>Expires</th>"
    "</tr></thead><tbody>"
    "<tr><td>X16</td><td>March 21, 2025</td><td>March 21, 2028</td></tr>"
    "<tr><td>X17</td><td>April 04, 2025</td><td>April 04, 2029</td></tr>"
    "</tbody></table></body></html>"
)


class RegistryBrowser:
    async def start(self):
        pass

    async def navigate_to(self, url):
        assert url == URL and self.navigation_scope(url)

    async def get_page(self):
        return self

    async def evaluate(self, _script, _limit):
        return {"url": URL, "html": HTML, "visible_html": HTML, "oversized": False}

    async def close(self):
        pass


def proposal(payload):
    rows = {}
    for source in payload["sources"]:
        if label := source.get("column_header"):
            rows.setdefault(source["scope"], {})[label] = source
    candidates = []
    for scope, row in rows.items():
        if row["Equipment"]["text"] not in payload["goal"]:
            continue
        assert row["Last Inspection"]["text"] != row["Expires"]["text"]
        fields = {"expiry_date": row["Expires"], "equipment": row["Equipment"]}
        candidates.append(
            {
                "scope": scope,
                "record": {k: s["text"] for k, s in fields.items()},
                "evidence": {
                    f"/{k}": {"source": s["id"], "quote": s["text"], "transform": "text"}
                    for k, s in fields.items()
                },
            }
        )
    assert len(candidates) == 2, "Visible row values must arrive with their column labels"
    return {"candidates": candidates}


async def test_saved_discovery_and_model_responses_survive_review_budget_pause(
    tmp_path, monkeypatch
):
    db_path = str(tmp_path / "run.db")
    config = Settings(
        _env_file=None,
        sqlite_db_path=db_path,
        search_provider="openai",
        openai_api_key="offline-test-key",
        search_request_budget=1,
        model_request_budget=60_000,
        action_delay_seconds=0,
        llm_min_interval_seconds=0,
        llm_retries=0,
    )
    calls = Counter()
    active_config = config

    def start_browser(config):
        nonlocal active_config
        active_config = config
        return RegistryBrowser()

    async def discover(query, _config, _payload, _report):
        calls["search"] += 1
        assert query.startswith("site:certification.example.test")
        return SearchObservation(
            provider="openai",
            query=query,
            results=[SearchResult(title="Official registry", url=URL)],
        )

    async def provider(messages, **_kwargs):
        system, payload = messages[0]["content"], json.loads(messages[1]["content"])
        if system.startswith(SEMANTIC_PLANNER):
            calls["plan"] += 1
            response = {
                "fields": [
                    {
                        "pointer": field["pointer"],
                        "temporal_class": "static",
                        "reference_period": "none",
                        "temporal_intent": None,
                        "definition_sensitive": False,
                        "unit_sensitive": False,
                        "comparable_across_rows": False,
                        "confidence": 1,
                    }
                    for field in payload["fields"]
                ]
            }
        elif system.startswith(PROPOSE):
            calls["proposal"] += 1
            response = proposal(payload)
        elif system.startswith(REVIEW):
            calls["review"] += 1
            by_id = {cell["id"]: cell for cell in payload["entity_context"]}
            for pointer, label in (("/equipment", "Equipment"), ("/expiry_date", "Expires")):
                proof = payload["candidate"]["evidence"][pointer]
                assert by_id[proof["source"]]["column_header"] == label
                assert by_id[proof["source"]]["text"] == proof["quote"]
            response = {
                "relevant": True,
                "same_entity": True,
                "supported_fields": payload["review_pointers"],
                "rejected_fields": [],
            }
            if calls["review"] == 1:
                # Use the ledger's actual reservation, so the next request is blocked
                # before transport regardless of harmless changes in prompt size.
                with closing(ResearchStore(db_path, read_only=True)) as store:
                    run = store.load(None)
                    active_config.model_request_budget = run["reserved"]
        else:
            assert system.startswith(SOURCE_ASSESSMENT_PROMPT)
            calls["assessment"] += 1
            response = {
                "candidates": [
                    {"candidate_index": candidate["candidate_index"], "assessments": []}
                    for candidate in payload["candidates"]
                ]
            }
        return SimpleNamespace(
            usage=SimpleNamespace(total_tokens=37),
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=json.dumps(response))
                )
            ],
        )

    monkeypatch.setattr("verboisy.core.research.BrowserManager", start_browser)
    monkeypatch.setattr("verboisy.core.search._openai_search_transport", discover)
    monkeypatch.setattr("verboisy.llm.client._complete", provider)
    path = tmp_path / "inspection.json"
    paused = await arun(
        goal="Find the inspection expiry dates for X16 and X17",
        schema="[equipment,expiry_date]",
        strings=True,
        include=["certification.example.test"],
        onlyinclude=True,
        identity=["/equipment"],
        maxrows=2,
        max_steps=1,
        proof=True,
        export=[path, tmp_path / "inspection.csv"],
        config=config,
    )
    assert (paused.status, paused.stop_reason) == ("PAUSED", "model_request_budget")
    assert calls == {"search": 1, "plan": 1, "proposal": 1, "review": 1}

    config.model_request_budget = 60_000
    result = await arun(resume=paused.run_id, config=config, max_steps=1)
    assert result.completed and result.proof_path is not None
    assert calls == {"search": 1, "plan": 1, "proposal": 1, "review": 2, "assessment": 1}
    assert {row["equipment"]: row["expiry_date"] for row in result.records} == {
        "X16": "March 21, 2028",
        "X17": "April 04, 2029",
    }
    assert URL in result.proof_path.read_text(encoding="utf-8")
    assert (tmp_path / "inspection.csv").is_file()
    with closing(ResearchStore(db_path, read_only=True)) as store:
        assert store.search_attempt_count(result.run_id) == 1
        assert store.load(result.run_id)["reserved"] < 60_000
