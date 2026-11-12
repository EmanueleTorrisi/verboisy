# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise exact source contracts, real rendering, and saved proof replay."""

import json
import os
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.api import arun
from verboisy.core.initial_discovery import discover_seed_sources
from verboisy.core.page_capture import CAPTURE_PAGE, capture_rendered_page
from verboisy.evidence.models import Candidate, Snapshot, TaskSpec
from verboisy.evidence.snapshot import canonical_url, snapshot
from verboisy.evidence.verify import verify
from verboisy.llm import client
from verboisy.research_contract import validate_research_contract
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError, VerboisyError

DECLARATION = {
    "region": "main#publication",
    "fields": {
        "title": {"selector": "h1"},
        "published": {"selector": "dl.metadata", "label": "Published"},
        "edition": {"selector": "dl.metadata", "label": "Edition", "on_missing": "null"},
    },
}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "published": {"type": "string"},
        "edition": {"type": ["string", "null"]},
    },
    "required": ["title", "published", "edition"],
    "additionalProperties": False,
}


def task(urls: list[str]) -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "seed_urls": urls,
            "target_records": len(urls),
            "identity_fields": ["/title"],
            "html_metadata": DECLARATION,
            "settle_ms": 0,
        }
    )


def markup(title: str, published: str, edition: str | None) -> str:
    detail = "" if edition is None else f"<dt>Edition</dt><dd>{edition}</dd>"
    return (
        '<html><head><style>.hidden {display: none}</style></head><body><main id="publication">'
        f'<h1>{title}</h1><h1 class="hidden">A layout decoy</h1>'
        f'<dl class="metadata"><dt>Published:</dt><dd>{published}</dd>{detail}</dl>'
        '<a href="/related">Related publication</a></main></body></html>'
    )


def test_contract_refuses_scope_changes_and_implicit_semantics() -> None:
    one = task(["https://example.test/first"])
    validate_research_contract(SCHEMA, one)
    validate_research_contract({"type": "array", "items": SCHEMA}, one)
    for update, message in (
        ({"seed_urls": []}, "canonical seeds"),
        ({"seed_urls": ["https://example.test"]}, "canonical seeds"),
        ({"seed_urls": ["https://example.test/first"] * 2}, "canonical seeds"),
        ({"target_records": 2}, "target record"),
        ({"identity_fields": []}, "explicit identity"),
        ({"identity_fields": ["/edition"]}, "nonmissing bindings"),
        ({"allow_nulls": False}, "schema allow it"),
    ):
        with pytest.raises(VerboisyError, match=message):
            validate_research_contract(SCHEMA, one.model_copy(update=update))
    for schema, message in (
        ({**SCHEMA, "additionalProperties": True}, "closed flat"),
        ({**SCHEMA, "required": ["title", "published"]}, "closed flat"),
        (
            {**SCHEMA, "properties": {**SCHEMA["properties"], "edition": {"type": "integer"}}},
            "literal string",
        ),
        (
            {**SCHEMA, "properties": {**SCHEMA["properties"], "edition": {"type": "string"}}},
            "schema allow it",
        ),
        (
            {
                **SCHEMA,
                "properties": {
                    **SCHEMA["properties"],
                    "published": {"type": "string", "x-verboisy-reference-period": "required"},
                },
            },
            "literal string",
        ),
    ):
        with pytest.raises(VerboisyError, match=message):
            validate_research_contract(schema, one)


async def test_declared_seeds_never_use_inline_urls_or_search() -> None:
    spec = task(["https://example.test/first"])
    search = AsyncMock(side_effect=AssertionError("search must not run"))
    inline = Mock(side_effect=AssertionError("inline URLs must not be followed"))
    policy = Mock()
    policy.permits.return_value = True
    result = await discover_seed_sources(
        "another page", spec, policy, Mock(), Mock(), search, inline, canonical_url
    )
    assert result == (spec.seed_urls, [])
    search.assert_not_called()
    inline.assert_not_called()
    policy.permits.return_value = False
    with pytest.raises(VerboisyError, match="seed conflicts"):
        await discover_seed_sources(
            "another page", spec, policy, Mock(), Mock(), search, inline, canonical_url
        )


async def test_capture_journals_layout_drift_and_refuses_the_page() -> None:
    url = "https://example.test/first"
    raw = markup(
        "Atlas", "11 Nov 2026", None
    )  # A second unmarked heading makes the binding ambiguous.
    runner = SimpleNamespace(
        task=task([url]),
        config=Settings(_env_file=None),
        rid="run",
        in_scope=lambda candidate: candidate == url,
        store=Mock(),
    )
    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={"url": url, "html": raw, "visible_html": raw, "oversized": False}
        )
    )
    with pytest.raises(NavigationError, match="rendered layout"):
        await capture_rendered_page(runner, page, canonical_url, snapshot, CAPTURE_PAGE)
    runner.store.event.assert_called_once_with(
        "run",
        "coverage_gap",
        {"reason": "html_metadata_layout", "detail": "field_region_not_unique"},
    )


@pytest.mark.browser
async def test_rendered_metadata_completes_without_a_model_and_replays(
    tmp_path, monkeypatch
) -> None:
    routes = {
        "/first": markup("Atlas release", "10 Nov 2026", None),
        "/second": markup("Boreal release", "11 Nov 2026", "003"),
        "/related": markup("Unrequested release", "12 Nov 2026", "004"),
    }
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits.append(self.path)
            if self.path not in routes:
                self.send_error(404)
                return
            data = routes[self.path].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    spec = task([origin + "/first", origin + "/second"])
    model = AsyncMock(side_effect=AssertionError("model calls are forbidden in literal HTML mode"))
    monkeypatch.setattr(client, "_complete", model)
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        allow_private_network=True,
        allowed_domains=["127.0.0.1"],
        browser_auto_install=False,
        browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
        action_delay_seconds=0,
        run_timeout_seconds=45,
    )
    output = tmp_path / "result.json"
    try:
        result = await arun(
            goal="Published metadata; do not traverse " + origin + "/related",
            schema=SCHEMA,
            task=spec,
            config=config,
            max_steps=2,
            export=output,
            proof=True,
            date_format="source",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    model.assert_not_called()
    assert result.completed and result.status == "COMPLETED"
    assert "/related" not in hits
    assert {
        row["title"]: (row["published"], row["edition"])
        for row in json.loads(output.read_text(encoding="utf-8"))
    } == {"Atlas release": ("10 Nov 2026", None), "Boreal release": ("11 Nov 2026", "003")}
    with closing(ResearchStore(str(result.db_path), read_only=True)) as store:
        state = store.load(result.run_id)
        assert state["tokens"] == state["reserved"] == 0
        assert not store.events(result.run_id, "extraction_proposal")
        assert not store.events(result.run_id, "search_request")
        assert len(store.events(result.run_id, "html_metadata_binding")) == 2
        entries = store.evidence(result.run_id)
        assert len(entries) == 2
        for entry in entries:
            candidate = Candidate.model_validate(entry["candidate"])
            page = Snapshot.model_validate(entry["snapshot"])
            assert not verify(candidate, page, SCHEMA, spec)
            tampered = candidate.model_copy(
                update={"record": {**candidate.record, "edition": "invented"}}
            )
            assert verify(tampered, page, SCHEMA, spec) == ["html_metadata_binding_mismatch"]
            damaged = page.model_copy(update={"sources": page.sources[:-1]})
            assert verify(candidate, damaged, SCHEMA, spec) == ["html_metadata_snapshot_invalid"]
