# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cross-schema acceptance contracts using controlled model responses, not live-model claims."""

import csv
import json
import sqlite3
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from verboisy import arun, run
from verboisy.evidence.models import Candidate, FieldRule, Proof, TaskSpec
from verboisy.evidence.snapshot import canonical_url, chunks, snapshot
from verboisy.evidence.verify import leaves, lookup, verify
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.llm.client import LLMClient
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import BudgetExceededError, LLMError, NavigationError, VerboisyError

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"customer": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["customer", "age"],
        "additionalProperties": False,
    },
}
PAGES = {
    "https://people.test/": '<a href="/a">Alice</a><a href="/b">Bob</a>',
    "https://people.test/a": '<article><h1>Alice</h1><p>31</p></article><a href="/">Back</a>',
    "https://people.test/b": '<article><h1>Bob</h1><p>22</p></article><a href="/">Back</a>',
}


def task(**kwargs):
    return {
        "seed_urls": ["https://people.test/"],
        "target_records": 2,
        "identity_fields": ["/customer"],
        "settle_ms": 0,
        **kwargs,
    }


async def test_bfs_pause_resume_exports_and_no_duplicate_visits(config, world, tmp_path):
    first = await arun(
        goal="Find customers",
        schema=SCHEMA,
        task=task(),
        export=tmp_path / "data.json",
        max_steps=2,
        config=config,
    )
    assert first.status == "PAUSED"
    assert [{k: v for k, v in row.items() if k != "id"} for row in first.records] == [
        {"customer": "Alice", "age": 31}
    ]
    first_id = first.records[0]["id"]
    assert json.loads(first.export_path.read_text()) == first.records
    final = await arun(resume=first.run_id, config=config)
    assert final.completed
    assert [{k: v for k, v in row.items() if k != "id"} for row in final.records] == [
        {"customer": "Alice", "age": 31},
        {"customer": "Bob", "age": 22},
    ]
    assert final.records[0]["id"] == first_id
    assert [c.args[0] for c in world.navigate_to.await_args_list] == list(PAGES)
    calls = world.start.await_count
    exported = await arun(resume=first.run_id, export=tmp_path / "data.csv", config=config)
    assert world.start.await_count == calls and exported.completed
    with exported.export_path.open() as f:
        rows = [{k: json.loads(v) for k, v in row.items() if v} for row in csv.DictReader(f)]
    assert rows == final.records
    report = json.loads(exported.manifest_path.read_text())
    assert report["collection_schema_valid"] and not report["global_completeness_claimed"]
    proof = json.loads((tmp_path / "data.csv.evidence.json").read_text())
    assert proof[0]["snapshot"]["url"] == "https://people.test/a"
    assert report["goal"] == "Find customers"
    assert len(report["model_invocations"]) == 2
    import hashlib

    store = ResearchStore(config.sqlite_db_path)
    rows = store.db.execute("SELECT payload,visible_html FROM snapshots").fetchall()
    assert all(
        json.loads(r[0])["content_hash"] == hashlib.sha256(r[1].encode()).hexdigest() for r in rows
    )
    store.close()


@pytest.mark.parametrize(
    "policy,reason",
    [
        ({"max_depth": 0}, "coverage_or_identity_gaps"),
        ({"max_pages": 1}, "page_budget"),
        ({"allowed_hosts": ["other.test"]}, "coverage_or_identity_gaps"),
        ({"include_paths": ["/none"]}, "coverage_or_identity_gaps"),
        ({"exclude_paths": ["/*"]}, "coverage_or_identity_gaps"),
        ({"target_records": 3}, "observed_scope_exhausted"),
        ({"target_records": None}, "observed_scope_exhausted"),
        ({"max_links_per_page": 1, "target_records": 3}, "coverage_or_identity_gaps"),
    ],
)
async def test_scope_and_limits_never_claim_complete(config, world, policy, reason):
    result = await arun(goal="Find", schema=SCHEMA, task=task(**policy), config=config)
    assert not result.completed and result.stop_reason == reason


@pytest.mark.parametrize(
    "failure,status,reason",
    [
        (LLMError("HTTP 429; quota"), "FAILED", "429"),
        (BudgetExceededError("limit"), "PAUSED", "model_request_budget"),
        (TimeoutError(), "PAUSED", "run_timeout"),
        (ValueError("secret"), "FAILED", "execution_ValueError"),
    ],
)
async def test_model_failure_is_saved_and_exports_partial(
    config, world, monkeypatch, tmp_path, failure, status, reason
):
    monkeypatch.setattr(
        "verboisy.llm.client.LLMClient.complete_json", AsyncMock(side_effect=failure)
    )
    result = await arun(
        goal="Find", schema=SCHEMA, task=task(), export=tmp_path / "partial.json", config=config
    )
    assert result.status == status and reason in result.stop_reason
    assert result.export_path.exists() and "secret" not in result.stop_reason


async def test_navigation_error_remains_retryable(config, world):
    world.navigate_to.side_effect = NavigationError("private")
    result = await arun(goal="x", schema=SCHEMA, task=task(), config=config)
    assert result.status == "FAILED" and result.stop_reason == "source_failures"
    s = ResearchStore(config.sqlite_db_path)
    assert s.summary(result.run_id)["pages"] == {"failed": 1}
    s.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"goal": "x"},
        {"goal": " ", "schema": {}},
        {"goal": "x", "schema": {}, "max_steps": False},
        {"goal": "x", "schema": {}, "max_steps": 0},
        {"resume": ""},
        {"resume": 3},
        {"resume": True, "goal": "new"},
        {"goal": "x", "schema": {}, "export": "bad.txt"},
        {"goal": "x", "schema": {}, "task": {"seed_urls": ["file:///etc/passwd"]}},
        {"goal": "x", "schema": {}, "task": {"target_records": -1}},
        {"goal": "x", "schema": "missing.json"},
    ],
)
async def test_invalid_inputs_launch_nothing(config, world, kwargs):
    with pytest.raises(VerboisyError):
        await arun(config=config, **kwargs)
    world.start.assert_not_awaited()


async def test_input_collision_and_legacy_preservation(config, tmp_path, world):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA))
    with pytest.raises(VerboisyError, match="differ"):
        await arun(goal="x", schema=path, export=path, config=config)
    dbpath = tmp_path / "legacy.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE runs(id TEXT)")
    original = dbpath.read_bytes()
    config.sqlite_db_path = str(dbpath)
    with pytest.raises(VerboisyError, match="Legacy"):
        await arun(resume=True, config=config)
    assert dbpath.read_bytes() == original
    with pytest.raises(VerboisyError, match="await arun"):
        run(goal="x", schema={})


def test_cross_schema_nested_values_unicode_and_entity_boundaries():
    html = (
        "<table>"
        "<tr>"
        "<td>Café β</td>"
        "<td>42 true 3.5</td>"
        "<td>"
        '<a href="https://vendor.test/a">Vendor</a>'
        "</td>"
        "</tr>"
        "<tr>"
        "<td>Someone else</td>"
        "</tr>"
        "</table>"
    )
    page = snapshot(html, "https://catalog.test/")
    s = {s.text: s for s in page.sources}
    c = Candidate(
        scope=s["Café β"].scope,
        record={
            "label": "Café β",
            "count": 42,
            "nested": {"a/b": True},
            "list": [3.5],
            "link": "https://vendor.test/a",
            "unknown": None,
        },
        evidence={
            "/label": Proof(source=s["Café β"].id, quote="Café β"),
            "/count": Proof(source=s["42 true 3.5"].id, quote="42", transform="integer"),
            "/nested/a~1b": Proof(source=s["42 true 3.5"].id, quote="true", transform="boolean"),
            "/list/0": Proof(source=s["42 true 3.5"].id, quote="3.5", transform="number"),
            "/link": Proof(source=s["Vendor"].id, transform="href"),
        },
    )
    assert not verify(c, page, {"type": "object"}, TaskSpec(identity_fields=["/label"]))
    assert lookup(c.record, "/nested/a~1b") is True and lookup(c.record, "/list/0") == 3.5
    assert "/nested/a~1b" in leaves(c.record)
    assert verify(c, page, {"type": "object"}, TaskSpec(allow_nulls=False))
    c.record["link"] = "https://invented.test/"
    assert "/link:url_not_observed" in verify(c, page, {"type": "object"}, TaskSpec())
    c.evidence["/label"] = Proof(source=s["Someone else"].id, quote="Someone else")
    assert "/label:source_outside_entity" in verify(c, page, {"type": "object"}, TaskSpec())


@pytest.mark.parametrize(
    "value,quote,transform,expected",
    [
        ("Made up", "Made up", "text", "quote_not_observed"),
        ("Other", "Alice", "text", "unsupported_value"),
        (2, "2", "integer", "quote_not_observed"),
        ("https://invented.test", "", "href", "url_not_observed"),
        (None, "Alice", "text", None),
        ([], "Alice", "text", "unsupported_value"),
        (True, "Alice", "boolean", "unsupported_value"),
        (42, "42", "integer", None),
        ("42", "42", "number", "unsupported_value"),
    ],
)
def test_literal_negative_controls(value, quote, transform, expected):
    page = snapshot("<p>Alice 42</p>", "https://data.test/")
    c = Candidate(
        scope="page",
        record={"f": value, "anchor": "Alice"},
        evidence={
            "/f": Proof(source=page.sources[0].id, quote=quote, transform=transform),
            "/anchor": Proof(source=page.sources[0].id, quote="Alice"),
        },
    )
    errors = verify(c, page, {"type": "object"}, TaskSpec())
    assert any(expected in e for e in errors) if expected else not errors


@pytest.mark.parametrize(
    "value,quote,transform,expected",
    [
        (2876591, "2,876,591", "integer", None),
        (1234.5, "1,234.50", "number", None),
        (1234567, "12,34,567", "integer", "unsupported_value"),
        (47400000, "47.4", "integer", "unsupported_value"),
    ],
)
def test_grouped_numeric_literals_are_strict(value, quote, transform, expected):
    page = snapshot(f"<p>{quote}</p>", "https://data.test/")
    candidate = Candidate(
        scope="page",
        record={"amount": value},
        evidence={
            "/amount": Proof(
                source=page.sources[0].id,
                quote=quote,
                transform=transform,
            )
        },
    )

    errors = verify(
        candidate,
        page,
        {"type": "object"},
        TaskSpec(),
    )

    assert any(expected in error for error in errors) if expected else not errors


def test_explicit_metadata_mapping_and_missing_identity():
    page = snapshot('<p>Available</p><a href="/a">same host</a>', "https://shop.test/")
    c = Candidate(
        scope="page",
        record={"in_stock": True},
        evidence={
            "/in_stock": Proof(source=page.sources[0].id, quote="Available", transform="boolean")
        },
    )
    assert verify(c, page, {"type": "object"}, TaskSpec())
    assert not verify(
        c,
        page,
        {"type": "object"},
        TaskSpec(field_rules={"/in_stock": FieldRule(mapping={"true": "Available"})}),
    )
    c.record = {"origin": page.url}
    c.evidence = {"/origin": Proof(source="page", transform="page_url")}
    assert verify(c, page, {"type": "object"}, TaskSpec())
    assert not verify(
        c, page, {"type": "object"}, TaskSpec(field_rules={"/origin": FieldRule(source="page_url")})
    )
    c.record = {"link": "https://shop.test/a"}
    c.evidence = {"/link": Proof(source=page.sources[1].id, transform="href")}
    assert verify(
        c, page, {"type": "object"}, TaskSpec(field_rules={"/link": FieldRule(external=True)})
    )
    assert verify(c, page, {"type": "object"}, TaskSpec(identity_fields=["/missing"]))


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://EXAMPLE.test:443/a#x", "https://example.test/a"),
        ("https://example.test/#/app", "https://example.test/#/app"),
        ("https://u:p@example.test", None),
        ("javascript:x", None),
        ("http://[bad", None),
        ("https://example.test:bad", None),
        ("https://example.test/\n", None),
        ("/a", "https://base.test/a"),
        ("http://[::1]:9000/", "http://[::1]:9000/"),
    ],
)
def test_canonical_urls(url, expected):
    assert canonical_url(url, "https://base.test/") == expected


def test_snapshot_bounded_complete_objects_and_invisible_nodes():
    page = snapshot(
        "<div hidden>"
        "<span>hide</span>"
        "</div>"
        '<div style="display:none">hide2</div>'
        "<script>injection</script>"
        "<article>"
        "<p>A</p>"
        "</article>"
        "<article>"
        "<p>B</p>"
        "</article>"
        '<a href="javascript:x">bad</a>',
        "https://data.test/",
    )
    assert [s.text for s in page.sources] == ["A", "B"]
    assert len(chunks(page, 100)) == 2
    assert snapshot("<p>A</p>", page.url, 1).truncated
    with pytest.raises(ValueError):
        chunks(page, 1)


async def test_semantic_review_veto_and_invalid_action(config, model_script):
    page = snapshot("<p>Founder social profile</p>", "https://org.test/")
    engine = EvidenceExtractor(
        LLMClient(config=config), {"type": "object"}, TaskSpec(), "company websites"
    )
    c = Candidate(
        scope="page",
        record={"title": "Founder social profile"},
        evidence={"/title": Proof(source=page.sources[0].id, quote="Founder social profile")},
    )
    model_script(
        {
            "relevant": False,
            "same_entity": True,
            "supported_fields": ["/title"],
            "rejected_fields": [],
        }
    )
    assert await engine.check(c, page) == ["semantic_review_rejected"]
    c.record["title"] = "fabricated"
    fake = model_script()
    assert await engine.check(c, page)
    fake.assert_not_awaited()
    model_script({"action": "FINISH"})
    with pytest.raises(ValidationError):
        await engine.propose(page, page.sources)


def test_conflict_quarantines_both_versions_and_lock(tmp_path):
    store = ResearchStore(str(tmp_path / "runs.db"))
    with pytest.raises(VerboisyError, match="in use"):
        ResearchStore(str(tmp_path / "runs.db"))
    with pytest.raises(VerboisyError, match="No saved"):
        store.load(None)
    spec = TaskSpec(identity_fields=["/id"])
    rid = store.create("data", {"type": "object"}, spec, None)
    store.queue(rid, "https://data.test/", 0, None)
    page = snapshot("<p>A</p>", "https://data.test/")
    work = store.next_page(rid)
    store.snapshot(rid, work["id"], page, "<p>A</p>")
    c = Candidate(scope="page", record={"id": "A", "n": 1}, evidence={})
    assert store.accept(rid, page, c, [], spec) == "accepted"
    assert store.accept(rid, page, c, [], spec) == "duplicate"
    c.record["n"] = 2
    assert store.accept(rid, page, c, [], spec) == "rejected" and store.records(rid) == []
    c.record["n"] = 1
    assert store.accept(rid, page, c, [], spec) == "rejected"
    assert store.summary(rid)["identity_conflicts"] == 1
    store.db.execute("UPDATE research_meta SET version=100")
    store.db.commit()
    store.close()
    with pytest.raises(VerboisyError, match="version"):
        ResearchStore(str(tmp_path / "runs.db"))


@pytest.mark.parametrize(
    "text,quote,value",
    [
        ("3.5", "5", 5),
        ("3.5", "3", 3),
        ("1,200", "200", 200),
        ("-100", "100", 100),
        ("\u2212100", "100", 100),
        ("+100", "100", 100),
    ],
)
def test_numeric_proofs_cannot_drop_signs_or_take_decimal_fragments(text, quote, value):
    page = snapshot(f"<p>{text}</p>", "https://numbers.test/")
    candidate = Candidate(
        scope="page",
        record={"amount": value},
        evidence={
            "/amount": Proof(source=page.sources[0].id, quote=quote, transform="integer"),
        },
    )
    assert "/amount:quote_not_observed" in verify(candidate, page, {"type": "object"}, TaskSpec())


@pytest.mark.parametrize(
    "text,quote,value", [("Price: $100.", "100", 100), ("Amount: -100", "-100", -100)]
)
def test_numeric_proofs_accept_whole_signed_literals_and_sentence_punctuation(text, quote, value):
    page = snapshot(f"<p>{text}</p>", "https://numbers.test/")
    candidate = Candidate(
        scope="page",
        record={"amount": value},
        evidence={
            "/amount": Proof(source=page.sources[0].id, quote=quote, transform="integer"),
        },
    )
    assert verify(candidate, page, {"type": "object"}, TaskSpec()) == []


def test_product_attribute_rows_inherit_containing_entity_scope():
    page = snapshot(
        """
        <article>
          <h1>Book A</h1>
          <table>
            <tr><th>UPC</th><td>AAA111</td></tr>
            <tr><th>Price</th><td>10.00</td></tr>
          </table>
        </article>
        <article>
          <h1>Book B</h1>
          <table>
            <tr><th>UPC</th><td>BBB222</td></tr>
            <tr><th>Price</th><td>20.00</td></tr>
          </table>
        </article>
        """,
        "https://books.test/",
    )
    sources = {source.text: source for source in page.sources}

    # Attribute rows nested inside a product belong to that product.
    assert sources["Book A"].scope == sources["AAA111"].scope
    assert sources["Book A"].scope == sources["10.00"].scope
    assert sources["Book B"].scope == sources["BBB222"].scope
    assert sources["Book B"].scope == sources["20.00"].scope

    # Separate products remain separate provenance boundaries.
    assert sources["Book A"].scope != sources["Book B"].scope

    candidate = Candidate(
        scope=sources["Book A"].scope,
        record={
            "title": "Book A",
            "upc": "AAA111",
            "price": 10.0,
        },
        evidence={
            "/title": Proof(
                source=sources["Book A"].id,
                quote="Book A",
            ),
            "/upc": Proof(
                source=sources["AAA111"].id,
                quote="AAA111",
            ),
            "/price": Proof(
                source=sources["10.00"].id,
                quote="10.00",
                transform="number",
            ),
        },
    )

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "upc": {"type": "string"},
            "price": {"type": "number"},
        },
        "required": ["title", "upc", "price"],
        "additionalProperties": False,
    }

    assert verify(candidate, page, schema, TaskSpec()) == []

    # Evidence from another product must still fail.
    candidate.record["upc"] = "BBB222"
    candidate.evidence["/upc"] = Proof(
        source=sources["BBB222"].id,
        quote="BBB222",
    )

    assert "/upc:source_outside_entity" in verify(
        candidate,
        page,
        schema,
        TaskSpec(),
    )


def test_deferred_frontier_is_used_only_after_queued_work(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "deferred-frontier.db"))

    try:
        rid = store.create(
            "goal",
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
            TaskSpec(),
            None,
        )

        store.defer(
            rid,
            "https://example.com/deferred",
            1,
            "https://example.com/",
        )
        store.queue(
            rid,
            "https://example.com/queued",
            0,
            None,
        )

        first = store.next_page(rid)
        assert first is not None
        assert first["url"] == ("https://example.com/queued")

        store.mark_page(
            first["id"],
            "done",
        )

        second = store.next_page(rid)
        assert second is not None
        assert second["url"] == ("https://example.com/deferred")

    finally:
        store.close()


def test_queue_promotes_previously_deferred_url(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "promoted-frontier.db"))

    try:
        rid = store.create(
            "goal",
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
            TaskSpec(),
            None,
        )

        url = "https://example.com/later"

        store.defer(
            rid,
            url,
            1,
            "https://example.com/",
        )

        assert store.summary(rid)["pages"]["deferred"] == 1

        store.queue(
            rid,
            url,
            1,
            "https://example.com/",
        )

        assert store.summary(rid)["pages"]["queued"] == 1

        work = store.next_page(rid)
        assert work is not None
        assert work["url"] == url

    finally:
        store.close()


def test_negative_queued_source_yields_to_deferred_fallback(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "productive-frontier.db"))

    try:
        rid = store.create(
            "goal",
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
            TaskSpec(),
            None,
        )

        store.queue(
            rid,
            "https://bad.test/child",
            1,
            "https://bad.test/",
        )
        store.defer(
            rid,
            "https://fresh.test/",
            0,
            None,
        )

        work = store.next_page(
            rid,
            {
                "bad.test": -0.25,
            },
        )

        assert work is not None
        assert work["url"] == "https://fresh.test/"

    finally:
        store.close()


def test_productive_queued_source_stays_ahead_of_fallback(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "productive-source.db"))

    try:
        rid = store.create(
            "goal",
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
            TaskSpec(),
            None,
        )

        store.queue(
            rid,
            "https://good.test/child",
            1,
            "https://good.test/",
        )
        store.defer(
            rid,
            "https://fresh.test/",
            0,
            None,
        )

        work = store.next_page(
            rid,
            {
                "good.test": 0.25,
            },
        )

        assert work is not None
        assert work["url"] == "https://good.test/child"

    finally:
        store.close()


def test_rebalance_frontier_demotes_legacy_queue_overflow(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "rebalance.db"))

    try:
        rid = store.create(
            "goal",
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
            TaskSpec(),
            None,
        )

        # Insert a deeper page first to prove depth takes
        # precedence over insertion order.
        store.queue(
            rid,
            "https://example.test/deep",
            1,
            "https://example.test/",
        )
        store.queue(
            rid,
            "https://one.test/",
            0,
            None,
        )
        store.queue(
            rid,
            "https://two.test/",
            0,
            None,
        )
        store.queue(
            rid,
            "https://three.test/",
            0,
            None,
        )

        result = store.rebalance_frontier(
            rid,
            active_limit=2,
        )

        assert result == {
            "queued": 2,
            "demoted": 2,
        }

        pages = {page["url"]: page["status"] for page in store.pages(rid)}

        assert pages == {
            "https://example.test/deep": "deferred",
            "https://one.test/": "queued",
            "https://two.test/": "queued",
            "https://three.test/": "deferred",
        }

    finally:
        store.close()


def test_recover_requeues_active_but_preserves_failed_page(
    tmp_path,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(str(tmp_path / "recover-state.db"))

    try:
        rid = store.create(
            "goal",
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
            TaskSpec(),
            None,
        )

        store.queue(
            rid,
            "https://active.test/",
            0,
            None,
        )
        active = store.next_page(rid)
        assert active is not None

        store.queue(
            rid,
            "https://failed.test/",
            0,
            None,
        )
        failed = store.next_page(rid)
        assert failed is not None

        store.mark_page(
            failed["id"],
            "failed",
            "browser_error",
        )

        store.recover(rid)

        pages = {
            page["url"]: (
                page["status"],
                page["reason"],
            )
            for page in store.pages(rid)
        }

        assert pages["https://active.test/"] == (
            "queued",
            None,
        )
        assert pages["https://failed.test/"] == (
            "failed",
            "browser_error",
        )

    finally:
        store.close()


def test_table_header_row_is_not_an_entity_scope():
    page = snapshot(
        """
        <table>
          <tr>
            <th>Country</th>
            <th>Population</th>
          </tr>
          <tr>
            <td>Canada</td>
            <td>41,651,653</td>
          </tr>
        </table>
        """,
        "https://data.test/",
    )
    sources = {source.text: source for source in page.sources}

    assert sources["Country"].scope == "page"
    assert sources["Population"].scope == "page"
    assert sources["Canada"].scope != "page"
    assert sources["41,651,653"].scope == sources["Canada"].scope


def _supersession_candidate(
    population,
    year,
):
    from verboisy.evidence.models import (
        Candidate,
        TemporalProof,
    )

    return Candidate(
        scope="s1",
        record={
            "customer": "same-id",
            "population": population,
        },
        evidence={},
        temporal_evidence={
            "/population": TemporalProof(
                source="e1",
                quote=str(year),
                reference_year=year,
            )
        },
    )


def _supersession_snapshot(
    sid,
    url,
):
    from verboisy.evidence.models import Snapshot

    return Snapshot(
        id=sid,
        url=url,
        fetched_at=("2026-09-30T12:00:00+00:00"),
        content_hash=sid,
        sources=[],
        truncated=False,
    )


def test_store_supersedes_record_without_changing_stable_id(
    config,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(config.sqlite_db_path)

    task = TaskSpec(identity_fields=["/customer"])
    schema = {
        "type": "object",
        "properties": {
            "customer": {"type": "string"},
            "population": {"type": "integer"},
        },
    }

    try:
        rid = store.create(
            "Find latest population",
            schema,
            task,
            None,
        )

        store.queue(
            rid,
            "https://example.test/",
            0,
            None,
        )
        work = store.next_page(rid)
        assert work is not None

        old = _supersession_candidate(
            100,
            2022,
        )
        new = _supersession_candidate(
            110,
            2025,
        )

        first_page = _supersession_snapshot(
            "snapshot-old",
            "https://example.test/old",
        )
        second_page = _supersession_snapshot(
            "snapshot-new",
            "https://example.test/new",
        )

        store.snapshot(
            rid,
            work["id"],
            first_page,
            "<html></html>",
        )
        store.snapshot(
            rid,
            work["id"],
            second_page,
            "<html></html>",
        )

        assert (
            store.accept(
                rid,
                first_page,
                old,
                [],
                task,
            )
            == "accepted"
        )

        original = store.records(rid)
        assert len(original) == 1
        stable_id = original[0]["id"]

        assert (
            store.accepted_candidate(
                rid,
                new,
                task,
            )
            == old
        )

        assert (
            store.accept(
                rid,
                second_page,
                new,
                [],
                task,
                preference="new",
            )
            == "accepted"
        )

        rows = store.records(rid)

        assert rows == [
            {
                "id": stable_id,
                "customer": "same-id",
                "population": 110,
            }
        ]

        assert store.summary(rid)["identity_conflicts"] == 0

        events = store.events(
            rid,
            "candidate_superseded",
        )

        assert len(events) == 1
        assert events[0]["payload"]["stable_id"] == stable_id

        candidates = store.db.execute(
            """
            SELECT accepted,reasons
            FROM candidates
            WHERE run_id=?
            ORDER BY id
            """,
            (rid,),
        ).fetchall()

        assert [row["accepted"] for row in candidates] == [0, 1]

        assert "superseded_candidate" in candidates[0]["reasons"]

    finally:
        store.close()


def test_store_rejects_older_candidate_without_creating_conflict(
    config,
):
    from verboisy.evidence.models import TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore(config.sqlite_db_path)

    task = TaskSpec(identity_fields=["/customer"])
    schema = {
        "type": "object",
        "properties": {
            "customer": {"type": "string"},
            "population": {"type": "integer"},
        },
    }

    try:
        rid = store.create(
            "Find latest population",
            schema,
            task,
            None,
        )

        store.queue(
            rid,
            "https://example.test/",
            0,
            None,
        )
        work = store.next_page(rid)
        assert work is not None

        current = _supersession_candidate(
            110,
            2025,
        )
        stale = _supersession_candidate(
            100,
            2022,
        )

        current_page = _supersession_snapshot(
            "snapshot-current",
            "https://example.test/current",
        )
        stale_page = _supersession_snapshot(
            "snapshot-stale",
            "https://example.test/stale",
        )

        store.snapshot(
            rid,
            work["id"],
            current_page,
            "<html></html>",
        )
        store.snapshot(
            rid,
            work["id"],
            stale_page,
            "<html></html>",
        )

        assert (
            store.accept(
                rid,
                current_page,
                current,
                [],
                task,
            )
            == "accepted"
        )

        before = store.records(rid)

        assert (
            store.accept(
                rid,
                stale_page,
                stale,
                [],
                task,
                preference="old",
            )
            == "rejected"
        )

        assert store.records(rid) == before
        assert store.summary(rid)["identity_conflicts"] == 0

        latest = store.db.execute(
            """
            SELECT accepted,reasons
            FROM candidates
            WHERE run_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (rid,),
        ).fetchone()

        assert latest["accepted"] == 0
        assert "superseded_candidate" in latest["reasons"]

    finally:
        store.close()


def test_accepted_candidate_without_identity_fields_returns_none():
    from verboisy.evidence.models import Candidate, TaskSpec
    from verboisy.storage.research import ResearchStore

    store = ResearchStore.__new__(ResearchStore)

    candidate = Candidate(
        scope="page",
        record={"name": "Example"},
        evidence={},
        temporal_evidence={},
    )

    assert (
        store.accepted_candidate(
            "run",
            candidate,
            TaskSpec(),
        )
        is None
    )
