# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Tests for versioned storage additions and human-readable proof export."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from verboisy.evidence.models import Candidate, Proof, TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.storage.proof import export_proof
from verboisy.storage.research import DB_VERSION, ResearchStore
from verboisy.utils.exceptions import VerboisyError

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


def _accepted_store(path: Path) -> tuple[ResearchStore, str]:
    store = ResearchStore(str(path))
    task = TaskSpec(seed_urls=["https://example.test/"], identity_fields=["/name"], settle_ms=0)
    rid = store.create("Find names", SCHEMA, task, None)
    store.queue(rid, "https://example.test/", 0, None)
    work = store.next_page(rid)
    assert work is not None
    page = snapshot("<article><h1>Alice</h1></article>", "https://example.test/")
    store.snapshot(rid, work["id"], page, "<article><h1>Alice</h1></article>")
    source = next(item for item in page.sources if item.text == "Alice")
    candidate = Candidate(
        scope=source.scope,
        record={"name": "Alice"},
        evidence={"/name": Proof(source=source.id, quote="Alice")},
    )
    assert store.accept(rid, page, candidate, [], task) == "accepted"
    store.mark_page(work["id"], "done")
    store.event(rid, "run_config", {"model": "test"})
    store.event(rid, "source_discovery", {"query": "names"})
    store.finish(rid, "COMPLETED", "target_met", 12, 0)
    return store, rid


def test_proof_report_reconstructs_persisted_facts(tmp_path: Path):
    store, rid = _accepted_store(tmp_path / "proof.db")
    try:
        output = export_proof(
            store,
            rid,
            tmp_path / "people.csv",
            notices=["Applied ordering: name ascending"],
            smartid_decisions=[{"new_id": "n1", "outcome": "exact"}],
        )
        text = output.read_text(encoding="utf-8")
        assert "Verboisy proof report" in text
        assert f"Run ID: {rid}" in text
        assert "COMPLETED" in text
        assert "done: https://example.test/" in text
        assert "Source: https://example.test/" in text
        assert 'quote="Alice"' in text
        assert "source_discovery" in text
        assert "run_config" not in text
        assert "transform: Applied ordering" in text
        assert 'smartid: {"new_id": "n1", "outcome": "exact"}' in text
    finally:
        store.close()


def test_proof_report_handles_no_accepted_records(tmp_path: Path):
    store = ResearchStore(str(tmp_path / "empty.db"))
    try:
        rid = store.create("Nothing", SCHEMA, TaskSpec(), None)
        store.finish(rid, "PAUSED", "observed_scope_exhausted", 0, 0)
        output = export_proof(store, rid, tmp_path / "empty.json")
        assert "No accepted records were persisted." in output.read_text(encoding="utf-8")
    finally:
        store.close()


def test_v2_database_migrates_stable_ids(tmp_path: Path):
    path = tmp_path / "v2.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE research_meta(version INTEGER NOT NULL);
            INSERT INTO research_meta VALUES(2);
            CREATE TABLE research_runs(
              id TEXT PRIMARY KEY, goal TEXT, schema_json TEXT, task_json TEXT,
              status TEXT, reason TEXT, tokens INTEGER DEFAULT 0,
              reserved INTEGER DEFAULT 0, export_path TEXT
            );
            CREATE TABLE pages(
              id INTEGER PRIMARY KEY, run_id TEXT, url TEXT, parent_url TEXT,
              depth INTEGER, status TEXT DEFAULT 'queued', reason TEXT,
              UNIQUE(run_id,url)
            );
            CREATE TABLE snapshots(
              id TEXT PRIMARY KEY, run_id TEXT, page_id INTEGER,
              payload TEXT, html TEXT, visible_html TEXT
            );
            CREATE TABLE candidates(
              id INTEGER PRIMARY KEY, run_id TEXT, snapshot_id TEXT,
              payload TEXT, reasons TEXT, accepted INTEGER
            );
            CREATE TABLE records(
              id INTEGER PRIMARY KEY, run_id TEXT, identity TEXT,
              payload TEXT, candidate_id INTEGER, UNIQUE(run_id,identity)
            );
            CREATE TABLE conflicts(run_id TEXT, identity TEXT, PRIMARY KEY(run_id,identity));
            CREATE TABLE events(
              id INTEGER PRIMARY KEY, run_id TEXT, kind TEXT, payload TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO records(run_id,identity,payload) VALUES('run','key','{\"name\":\"A\"}');
            """
        )
    store = ResearchStore(str(path))
    try:
        version = store.db.execute("SELECT version FROM research_meta").fetchone()[0]
        row = store.db.execute("SELECT stable_id FROM records").fetchone()
        assert version == DB_VERSION
        assert row[0] and len(row[0]) == 32
    finally:
        store.close()


def test_store_rejects_unknown_database_version(tmp_path: Path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE research_meta(version INTEGER NOT NULL)")
        db.execute("INSERT INTO research_meta VALUES(999)")
    with pytest.raises(VerboisyError, match="Unsupported"):
        ResearchStore(str(path))


def test_store_pages_events_and_missing_resume(tmp_path: Path):
    store = ResearchStore(str(tmp_path / "state.db"))
    try:
        with pytest.raises(VerboisyError, match="No saved"):
            store.load(None)
        rid = store.create("goal", SCHEMA, TaskSpec(), None)
        store.queue(rid, "https://example.test/", 0, None)
        work = store.next_page(rid)
        assert work is not None
        store.mark_page(work["id"], "failed", "temporary")
        store.recover(rid)
        assert store.next_page(rid) is None

        pages = store.pages(rid)
        assert pages[-1]["status"] == "failed"
        assert pages[-1]["reason"] == "temporary"
        store.event(rid, "note", {"x": 1})
        assert store.events(rid)[0]["payload"] == {"x": 1}
        assert store.pages(rid)[0]["status"] == "failed"
    finally:
        store.close()


def test_v2_migration_tolerates_preexisting_stable_id_column(tmp_path: Path):
    path = tmp_path / "partial-v2.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE research_meta(version INTEGER NOT NULL);
            INSERT INTO research_meta VALUES(2);
            CREATE TABLE research_runs(
              id TEXT PRIMARY KEY, goal TEXT, schema_json TEXT, task_json TEXT,
              status TEXT, reason TEXT, tokens INTEGER, reserved INTEGER, export_path TEXT
            );
            CREATE TABLE pages(
              id INTEGER PRIMARY KEY, run_id TEXT, url TEXT, parent_url TEXT,
              depth INTEGER, status TEXT, reason TEXT, UNIQUE(run_id,url)
            );
            CREATE TABLE snapshots(
              id TEXT PRIMARY KEY, run_id TEXT, page_id INTEGER, payload TEXT,
              html TEXT, visible_html TEXT
            );
            CREATE TABLE candidates(
              id INTEGER PRIMARY KEY, run_id TEXT, snapshot_id TEXT, payload TEXT,
              reasons TEXT, accepted INTEGER
            );
            CREATE TABLE records(
              id INTEGER PRIMARY KEY, run_id TEXT, identity TEXT, stable_id TEXT,
              payload TEXT, candidate_id INTEGER, UNIQUE(run_id,identity)
            );
            CREATE TABLE conflicts(run_id TEXT, identity TEXT, PRIMARY KEY(run_id,identity));
            CREATE TABLE events(
              id INTEGER PRIMARY KEY, run_id TEXT, kind TEXT, payload TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    store = ResearchStore(str(path))
    try:
        assert store.db.execute("SELECT version FROM research_meta").fetchone()[0] == DB_VERSION
    finally:
        store.close()


def test_proof_field_without_quote_is_rendered(tmp_path: Path):
    store = ResearchStore(str(tmp_path / "noquote.db"))
    try:
        task = TaskSpec(seed_urls=["https://example.test/"])
        rid = store.create("Link", SCHEMA, task, None)
        store.queue(rid, "https://example.test/", 0, None)
        work = store.next_page(rid)
        assert work is not None
        page = snapshot('<a href="https://vendor.test/a">Vendor</a>', "https://example.test/")
        store.snapshot(rid, work["id"], page, "<a>Vendor</a>")
        source = next(item for item in page.sources if item.kind == "link")
        candidate = Candidate(
            scope=source.scope,
            record={"name": "https://vendor.test/a"},
            evidence={"/name": Proof(source=source.id, transform="href")},
        )
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
        text = export_proof(store, rid, tmp_path / "link.json").read_text(encoding="utf-8")
        assert "transform=href" in text and "quote=" not in text
    finally:
        store.close()


@contextmanager
def normalization_store(tmp_path, record, pointer):
    from verboisy.core.source_assessment import (
        SourceAssessmentResponse,
        ground_source_assessments,
        source_fitness_event,
    )
    from verboisy.evidence.models import Snapshot, Source
    from verboisy.evidence.verify import leaves, verify

    store = ResearchStore(str(tmp_path / "normalization.db"))
    try:
        task = TaskSpec()
        schema = {"type": "object"}
        rid = store.create("Population", schema, task, None)
        values = leaves(record)
        sources = [
            Source(id=p, kind="text", scope="entity", text=str(v)) for p, v in values.items()
        ]
        quote = "Population in thousands of persons"
        sources.append(Source(id="unit", kind="text", scope="entity", text=quote))
        page = Snapshot(
            id="snapshot",
            url="https://example.test/",
            fetched_at="2026-10-03T00:00:00Z",
            content_hash="fixture",
            sources=sources,
            truncated=False,
        )
        candidate = Candidate(
            scope="entity",
            record=record,
            evidence={
                p: Proof(source=p, quote=str(v), transform="integer") for p, v in values.items()
            },
        )
        assert verify(candidate, page, schema, task) == []
        store.queue(rid, page.url, 0, None)
        work = store.next_page(rid)
        store.snapshot(rid, work["id"], page, "fixture")
        assert store.accept(rid, page, candidate, [], task) == "accepted"
        response = SourceAssessmentResponse.model_validate(
            {
                "assessments": [
                    {
                        "pointer": pointer,
                        "unit": {
                            "label": "thousands of persons",
                            "citation": {"source": "unit", "quote": quote},
                        },
                    }
                ]
            }
        )
        claims = ground_source_assessments(candidate, page, response)
        store.event(
            rid,
            "source_fitness",
            source_fitness_event(
                page,
                candidate,
                claims,
                cache_key="fixture",
                cache_hit=False,
            ),
        )
        record_id = store.evidence(rid)[0]["record_id"]
        yield store, rid, record_id
    finally:
        store.close()


def test_research_records_project_unit_normalization(tmp_path):
    from verboisy.core.units import canonical_unit, unit_normalization_event

    with normalization_store(tmp_path, {"population": 2}, "/population") as (store, rid, record_id):
        payload = unit_normalization_event(
            record_id=record_id,
            pointer="/population",
            original_value=2,
            unit=canonical_unit("thousands of persons"),
        )
        assert payload is not None
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid) == [{"id": record_id, **{"population": 2000}}]


def test_research_records_reject_tampered_normalization(tmp_path):
    from verboisy.core.units import canonical_unit, unit_normalization_event

    with normalization_store(tmp_path, {"population": 2}, "/population") as (store, rid, record_id):
        payload = unit_normalization_event(
            record_id=record_id,
            pointer="/population",
            original_value=2,
            unit=canonical_unit("thousands of persons"),
        )
        assert payload is not None
        payload["normalized_value"] = 999
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid) == [{"id": record_id, **{"population": 2}}]


def test_research_records_reject_stale_normalization(tmp_path):
    from verboisy.core.units import canonical_unit, unit_normalization_event

    with normalization_store(tmp_path, {"population": 3}, "/population") as (store, rid, record_id):
        payload = unit_normalization_event(
            record_id=record_id,
            pointer="/population",
            original_value=2,
            unit=canonical_unit("thousands of persons"),
        )
        assert payload is not None
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid) == [{"id": record_id, **{"population": 3}}]


def test_research_records_project_nested_unit_value(tmp_path):
    from verboisy.core.units import canonical_unit, unit_normalization_event

    with normalization_store(
        tmp_path, {"metrics": [{"population": 2}]}, "/metrics/0/population"
    ) as (store, rid, record_id):
        payload = unit_normalization_event(
            record_id=record_id,
            pointer="/metrics/0/population",
            original_value=2,
            unit=canonical_unit("thousands of persons"),
        )
        assert payload is not None
        store.event(rid, "unit_normalization", payload)
        assert store.records(rid) == [{"id": record_id, **{"metrics": [{"population": 2000}]}}]
