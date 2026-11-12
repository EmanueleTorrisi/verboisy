# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise the literal path in the ordinary offline suite with a rendered-page double."""

from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.api import arun
from verboisy.core import research
from verboisy.core.initial_discovery import publish_initial_discovery
from verboisy.core.planner import build_research_plan
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.verify import verify
from verboisy.llm import client
from verboisy.product import SourcePolicy
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

URLS = ["https://example.test/first", "https://example.test/second"]
OTHER = "https://example.test/other"
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 4},
        "edition": {"type": ["string", "null"]},
    },
    "required": ["title", "edition"],
    "additionalProperties": False,
}
TASK = TaskSpec.model_validate(
    {
        "seed_urls": URLS,
        "identity_fields": ["/title"],
        "target_records": 2,
        "max_pages": 2,
        "settle_ms": 0,
        "html_metadata": {
            "region": "main",
            "fields": {
                "title": {"selector": "h1"},
                "edition": {"selector": "span.edition", "on_missing": "null"},
            },
        },
    }
)


@pytest.mark.parametrize("case", ["complete", "layout_drift", "outside_redirect", "invalid_value"])
async def test_offline_literal_run_stays_grounded(tmp_path, monkeypatch, case):
    docs = {
        URLS[0]: "<html><body><main><h1>Atlas release</h1></main></body></html>",
        URLS[1]: (
            "<html><body><main><h1>Boreal release</h1>"
            '<span class="edition">007</span></main></body></html>'
        ),
    }
    if case == "layout_drift":
        docs[URLS[1]] = docs[URLS[1]].replace("</h1>", "</h1><h1>Ambiguous title</h1>")
    if case == "invalid_value":
        docs[URLS[1]] = docs[URLS[1]].replace("Boreal release", "A")
    visited = []

    class Browser:
        def __init__(self, **_kwargs):
            self.navigation_scope = None
            self.url = ""

        async def start(self):
            return self

        async def navigate_to(self, url):
            assert self.navigation_scope(url)
            visited.append(url)
            self.url = url

        async def get_page(self):
            return self

        async def evaluate(self, _script, _limit):
            body = docs[self.url]
            location = OTHER if case == "outside_redirect" and self.url == URLS[1] else self.url
            return {"url": location, "html": body, "visible_html": body, "oversized": False}

        async def close(self):
            pass

    monkeypatch.setattr(research, "BrowserManager", Browser)
    complete = AsyncMock(side_effect=AssertionError("The literal contract cannot call a model"))
    monkeypatch.setattr(client, "_complete", complete)
    config = Settings(
        _env_file=None, sqlite_db_path=str(tmp_path / "run.db"), action_delay_seconds=0
    )
    result = await arun(
        goal="Read the declared release pages only; ignore " + OTHER,
        schema=SCHEMA,
        task=TASK,
        config=config,
        max_steps=2,
    )
    complete.assert_not_called()
    assert sorted(visited) == sorted(URLS)
    assert result.completed is (case == "complete")
    with closing(ResearchStore(str(result.db_path), read_only=True)) as store:
        state = store.load(result.run_id)
        assert state["tokens"] == state["reserved"] == 0
        assert not store.events(result.run_id, "search_request")
        entries = store.evidence(result.run_id)
        assert len(entries) == (2 if case == "complete" else 1)
        (first,) = (
            entry for entry in entries if entry["candidate"]["record"]["title"] == "Atlas release"
        )
        candidate = Candidate.model_validate(first["candidate"])
        page = Snapshot.model_validate(first["snapshot"])
        assert candidate.record["edition"] is None and "/edition" not in candidate.evidence
        assert not verify(candidate, page, SCHEMA, TASK)
        assert verify(candidate, page.model_copy(update={"url": OTHER}), SCHEMA, TASK) == [
            "html_metadata_binding_mismatch"
        ]
        if case == "complete":
            assert any(entry["candidate"]["record"]["edition"] == "007" for entry in entries)
            bad = candidate.model_copy(update={"record": {**candidate.record, "edition": "guess"}})
            assert verify(bad, page, SCHEMA, TASK) == ["html_metadata_binding_mismatch"]
            assert verify(candidate, page.model_copy(update={"sources": []}), SCHEMA, TASK) == [
                "html_metadata_snapshot_invalid"
            ]
        elif case == "layout_drift":
            assert any(
                event["payload"].get("reason") == "html_metadata_layout"
                for event in store.events(result.run_id, "coverage_gap")
            )
        elif case == "outside_redirect":
            assert any(
                event["payload"]["reason"] == "navigation_failed"
                for event in store.events(result.run_id, "page_failure")
            )
            assert all(page["url"] != OTHER for page in store.pages(result.run_id))
        else:
            assert any(
                event["payload"]["outcome"] == "rejected"
                and "schema_invalid" in event["payload"]["reasons"]
                for event in store.events(result.run_id, "candidate")
            )


async def test_saved_discovery_cannot_add_an_unlisted_metadata_seed(tmp_path):
    with closing(ResearchStore(str(tmp_path / "run.db"))) as store:
        rid = store.create("Read the declared pages", SCHEMA, TASK, None)
        store.event(
            rid, "initial_discovery_result", {"seeds": [URLS[0], OTHER], "observations": []}
        )
        discover = AsyncMock(
            side_effect=AssertionError("Saved acquisition must not query a provider")
        )
        fake_client = SimpleNamespace(
            total_tokens=0, reserved_tokens=0, search_requests=0, on_usage=None
        )
        config = Settings(_env_file=None)
        with pytest.raises(VerboisyError, match="declared HTML metadata scope"):
            await publish_initial_discovery(
                store,
                rid,
                TASK,
                SourcePolicy(),
                config,
                build_research_plan(SCHEMA, 2),
                discover,
                Mock(return_value=fake_client),
            )
        assert not store.events(rid, "seed_frontier")
        assert not store.summary(rid)["pages"]
        assert TaskSpec.model_validate_json(store.load(rid)["task_json"]).seed_urls == URLS
        discover.assert_not_called()
