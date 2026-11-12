# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Check declared tables at configuration, replay and interruption boundaries."""

import asyncio
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from verboisy import api
from verboisy.core import research
from verboisy.core.initial_discovery import discover_seed_sources, publish_initial_discovery
from verboisy.core.planner import build_research_plan
from verboisy.evidence.html_metadata import MAX_TEXT_CHARS
from verboisy.evidence.html_table import HtmlTableError, HtmlTableSpec, literal_table_rows
from verboisy.evidence.html_table_snapshot import (
    _snapshot_id,
    html_table_candidate,
    html_table_candidates,
    html_table_snapshot,
)
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.llm import client
from verboisy.product import SourcePolicy
from verboisy.research_contract import validate_research_contract
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

URL = "https://inventory.example.test/list"
FOREIGN = "https://mirror.example.test/list"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"code": {"type": "integer"}, "description": {"type": "string"}},
    "required": ["code", "description"],
}
DECLARATION = {
    "selector": "table#registry",
    "key_field": "code",
    "keys": [11, 22],
    "fields": {
        "code": {"header": "Code", "value_type": "integer"},
        "description": {"header": "Description"},
    },
}
TABLE = HtmlTableSpec.model_validate(DECLARATION)
TASK = TaskSpec(
    html_table=TABLE,
    seed_urls=[URL],
    identity_fields=["/code"],
    target_records=2,
    max_pages=1,
    settle_ms=0,
)
HTML = """<table id="registry">
<caption>Stock</caption><colgroup><col><col></colgroup>
<script>doNotRun()</script>
<thead><tr><th>Code</th><th>Description</th></tr></thead>
<tbody><div hidden></div><tr><td>11</td><td>North</td></tr>
<tr><td>22</td><td>South</td></tr></tbody></table>"""


class TestDeclaredTableBoundaries(TestCase):
    def test_contract_rejects_ambiguous_columns_and_keys(self):
        cases = [
            ({"selector": "div#registry"}, "Select a table"),
            ({"fields": {"id": {"header": "Code"}}}, "id is reserved"),
            (
                {"fields": {"code": {"header": "Code"}, "code_2": {"header": "Code"}}},
                "distinct header",
            ),
            ({"fields": {"code": {"header": " Code "}}}, "normalized whitespace"),
            ({"key_field": "unbound"}, "bound key field"),
            ({"keys": [2**63]}, "signed 64-bit"),
            ({"keys": ["11"]}, "signed 64-bit"),
            ({"key_field": "description", "keys": ["two  spaces"]}, "Text keys"),
        ]
        for update, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValidationError, reason):
                HtmlTableSpec.model_validate({**DECLARATION, **update})

    def test_schema_must_be_literal_and_closed(self):
        with self.assertRaisesRegex(VerboisyError, "closed flat record schema"):
            validate_research_contract({**SCHEMA, "required": ["code"]}, TASK)
        properties = {
            **SCHEMA["properties"],
            "description": {"type": "string", "x-verboisy-temporal-class": "static"},
        }
        with self.assertRaisesRegex(VerboisyError, "explicit matching string or integer"):
            validate_research_contract({**SCHEMA, "properties": properties}, TASK)

    def test_table_refuses_structural_text_and_malformed_rows(self):
        assert literal_table_rows(HTML, TABLE) == [["11", "North"], ["22", "South"]]
        cases = [
            (HTML.replace("<tbody>", "<tbody>unexpected"), "unsupported_table_layout"),
            (
                HTML.replace("<caption>Stock</caption>", "<div>Stock</div>"),
                "unsupported_table_layout",
            ),
            (HTML.replace("<div hidden></div>", "<div>visible</div>"), "unsupported_table_layout"),
            (HTML.replace("<colgroup>", "<colgroup hidden>"), "unsupported_table_layout"),
            (HTML.removesuffix("</table>"), "unbalanced_layout"),
            (HTML.replace("South", "x" * (MAX_TEXT_CHARS + 1)), "blank_or_oversized_cell"),
        ]
        for html, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(HtmlTableError, reason):
                literal_table_rows(html, TABLE)

    def test_snapshot_requires_exact_row_coordinates_and_key_even_with_matching_digest(self):
        snapshot = html_table_snapshot(HTML, URL, 10_000, TABLE)
        for scope in ("foreign-0", "html-table-row-02", "html-table-row-2"):
            with (
                self.subTest(scope=scope),
                self.assertRaisesRegex(HtmlTableError, "invalid_table_scope"),
            ):
                html_table_candidate(snapshot, TABLE, scope)
        first, *rest = snapshot.sources
        for change, reason in (
            ({"id": "foreign"}, "invalid_table_source"),
            ({"scope": "html-table-row-1"}, "invalid_table_source"),
            ({"kind": "link", "href": URL}, "invalid_table_source"),
            ({"href": URL}, "invalid_table_source"),
            ({"text": "33"}, "table_key_binding_mismatch"),
        ):
            sources = [first.model_copy(update=change), *rest]
            digest = _snapshot_id(URL, snapshot.fetched_at, snapshot.content_hash, TABLE, sources)
            altered = snapshot.model_copy(update={"sources": sources, "id": digest})
            with self.subTest(change=change), self.assertRaisesRegex(HtmlTableError, reason):
                html_table_candidates(altered, TABLE)

    def test_completion_cannot_substitute_other_keys(self):
        runner = research.ResearchRunner.__new__(research.ResearchRunner)
        runner.task, runner.rid, runner.schema = TASK, "test", SCHEMA
        runner.store = Mock()
        runner.store.summary.return_value = {"identity_conflicts": 0}
        for rows in ([{"code": 11}, {"code": 99}], [{"code": 11}, {"code": 22}, {"code": 99}]):
            runner.store.records.return_value = rows
            assert not runner.target_met()

    def test_saved_rows_remain_bound_to_the_original_seed(self):
        snapshot = html_table_snapshot(HTML, URL, 10_000, TABLE)
        candidate = html_table_candidates(snapshot, TABLE)[0]
        with (
            TemporaryDirectory() as directory,
            closing(ResearchStore(str(Path(directory) / "research.db"))) as store,
        ):
            rid = store.create("Inventory", SCHEMA, TASK, None)
            store.queue(rid, URL, 0, None)
            page = store.next_page(rid)
            assert page is not None
            store.snapshot(rid, page["id"], snapshot, HTML, HTML)
            assert store.accept(rid, snapshot, candidate, [], TASK) == "accepted"
            store.update_task(rid, TASK.model_copy(update={"seed_urls": [FOREIGN]}))
            with self.assertRaisesRegex(VerboisyError, "outside its declared scope"):
                store.evidence(rid)


class TestDeclaredTableRecovery(IsolatedAsyncioTestCase):
    async def test_source_policy_and_saved_discovery_cannot_change_the_seed(self):
        config = Settings(_env_file=None)
        plan = build_research_plan(SCHEMA, 2)
        no_search = AsyncMock(side_effect=AssertionError("Declared table discovery cannot search"))
        inline = Mock(side_effect=AssertionError("The goal cannot supply new table URLs"))
        with self.assertRaisesRegex(VerboisyError, "seed conflicts with the source policy"):
            await discover_seed_sources(
                "Inventory",
                TASK,
                SourcePolicy(avoid=("inventory.example.test",)),
                config,
                plan,
                no_search,
                inline,
                canonical_url,
            )
        with (
            TemporaryDirectory() as directory,
            closing(ResearchStore(str(Path(directory) / "research.db"))) as store,
        ):
            rid = store.create("Inventory", SCHEMA, TASK, None)
            store.event(rid, "initial_discovery_result", {"seeds": [FOREIGN], "observations": []})
            stub = SimpleNamespace(total_tokens=0, reserved_tokens=0, search_requests=0)
            with self.assertRaisesRegex(VerboisyError, "declared HTML table scope"):
                await publish_initial_discovery(
                    store,
                    rid,
                    TASK,
                    SourcePolicy(),
                    config,
                    plan,
                    no_search,
                    Mock(return_value=stub),
                )
            assert not store.events(rid, "seed_frontier")
            assert not store.summary(rid)["pages"]
        no_search.assert_not_called()
        inline.assert_not_called()

    async def test_interrupted_table_can_resume_without_duplicate_rows_or_provider_calls(self):
        document = HTML.replace("<div hidden></div>", "")

        class Browser:
            def __init__(self, **_kwargs):
                self.navigation_scope = None

            async def start(self):
                return self

            async def navigate_to(self, url):
                assert url == URL and self.navigation_scope(url)

            async def get_page(self):
                return self

            async def evaluate(self, _script, _limit):
                return {"url": URL, "html": document, "visible_html": document, "oversized": False}

            async def close(self):
                pass

        actual_accept = ResearchStore.accept

        def interrupt(store, rid, page, candidate, *args, **kwargs):
            if candidate.record["code"] == 22:
                raise asyncio.CancelledError
            return actual_accept(store, rid, page, candidate, *args, **kwargs)

        blocked = AsyncMock(side_effect=AssertionError("A literal table must not use a provider"))
        with (
            TemporaryDirectory() as directory,
            patch.object(research, "BrowserManager", Browser),
            patch.object(client, "_complete", blocked),
            patch.object(api, "web_search", blocked),
            patch.object(research, "web_search", blocked),
        ):
            db = Path(directory) / "research.db"
            config = Settings(_env_file=None, sqlite_db_path=str(db), action_delay_seconds=0)
            started = []
            schema = {"type": "array", "items": SCHEMA, "minItems": 2, "uniqueItems": True}
            with (
                patch.object(ResearchStore, "accept", interrupt),
                self.assertRaises(asyncio.CancelledError),
            ):
                await api.arun(
                    goal="Inventory",
                    schema=schema,
                    task=TASK,
                    config=config,
                    max_steps=1,
                    on_started=lambda rid, _goal: started.append(rid),
                )
            (rid,) = started
            with closing(ResearchStore(str(db), read_only=True)) as store:
                assert store.load(rid)["status"] == "PAUSED"
                assert store.load(rid)["reason"] == "interrupted"
                (committed,) = store.records(rid)
                assert committed["code"] == 11
            result = await api.arun(resume=rid, config=config, max_steps=1)
            assert result.completed, result.stop_reason
            assert {record["code"] for record in result.records} == {11, 22}
            with closing(ResearchStore(str(db), read_only=True)) as store:
                events = store.events(rid, "candidate")
                assert [entry["payload"]["outcome"] for entry in events] == [
                    "accepted",
                    "duplicate",
                    "accepted",
                ]
                assert {row["code"]: row["id"] for row in store.records(rid)}[11] == committed["id"]
        blocked.assert_not_called()
