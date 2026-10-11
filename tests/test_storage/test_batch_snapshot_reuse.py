# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Batch reuse must reduce decoding without sharing mutable evidence or stale state."""

import asyncio
import json
from contextlib import closing

import pytest
from verboisy.evidence.models import Candidate, TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.extractor import range_changes as ranges
from verboisy.storage import saved_evidence
from verboisy.storage.research import ResearchStore, encode, lookup
from verboisy.utils.exceptions import VerboisyError

from tests.test_research.test_saved_range_resume_integrity import create, insert, state
from tests.test_storage.test_admission_transactions import SCHEMA


def batch(store):
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("People", SCHEMA, task, None)
    page = snapshot(
        "".join(
            f"<article><h1>{name}</h1><p>31</p></article>" for name in ["Alice", "Bob", "Céline"]
        ),
        "https://people.test/",
    )
    store.queue(rid, page.url, 0, None)
    pid = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()[0]
    store.snapshot(rid, pid, page, "fixture")
    for name in ["Alice", "Bob", "Céline"]:
        source = next(value for value in page.sources if value.text == name)
        age = next(
            value for value in page.sources if value.scope == source.scope and value.text == "31"
        )
        candidate = Candidate(
            scope=source.scope,
            record={"name": name, "age": 31},
            evidence={
                "/name": {"source": source.id, "quote": name},
                "/age": {"source": age.id, "quote": "31", "transform": "number"},
            },
        )
        store.accept(rid, page, candidate, [], task)
    return rid, page, task


def tracked_decoder(monkeypatch):
    calls = []
    original = saved_evidence._validated_snapshot_payload

    def tracked(row):
        calls.append((row["snapshot_id"], row["snapshot"]))
        return original(row)

    monkeypatch.setattr(saved_evidence, "_validated_snapshot_payload", tracked)
    return calls


@pytest.mark.parametrize("count", [2, 25, 100])
@pytest.mark.parametrize("kind", ["owned", "null", "missing", "foreign"])
def test_range_window_loads_each_reference_once_per_invocation(tmp_path, monkeypatch, count, kind):
    with closing(ResearchStore(tmp_path / "range.db")) as store:
        rid, page, candidate = create(store, interval=False)
        if kind == "foreign":
            _, page, _ = create(store, interval=False)
        elif kind == "missing":
            page = page.model_copy(update={"id": "missing"})
            store.db.execute("PRAGMA foreign_keys=OFF")
        elif kind == "null":
            page = None
        for _ in range(count):
            insert(store, rid, page, candidate.model_dump_json())
        store.db.execute("PRAGMA foreign_keys=ON")
        before = state(store)
        calls = []
        original = store.load_snapshot

        def tracked(run_id, snapshot_id):
            calls.append((run_id, snapshot_id))
            return original(run_id, snapshot_id)

        monkeypatch.setattr(store, "load_snapshot", tracked)
        for _ in range(2):
            evidence = ranges.saved_range_evidence(store, rid)
            assert len(evidence) == (count if kind == "owned" else 0)
        assert calls == [(rid, page.id if page is not None else None)] * 2
        assert state(store) == before


@pytest.mark.parametrize("mutation", ["page", "source", "sources"])
def test_reused_range_models_remain_independent_and_next_scan_is_fresh(tmp_path, mutation):
    with closing(ResearchStore(tmp_path / "models.db")) as store:
        rid, page, candidate = create(store, interval=False)
        for _ in range(3):
            insert(store, rid, page, candidate.model_dump_json())
        before = state(store)
        evidence = ranges.saved_range_evidence(store, rid)
        first = evidence[0][0]
        if mutation == "page":
            first.url = "https://changed.test/"
        elif mutation == "source":
            first.sources[0].text = "changed"
        else:
            first.sources.clear()
        assert all(item[0] == page for item in evidence[1:])
        assert all(item[0] == page for item in ranges.saved_range_evidence(store, rid))
        assert state(store) == before


@pytest.mark.parametrize("operation", ["range", "evidence"])
@pytest.mark.parametrize(
    "failure", [OSError, RuntimeError, KeyboardInterrupt, asyncio.CancelledError]
)
def test_interrupted_batch_retries_without_reusing_partial_cache(
    tmp_path, monkeypatch, operation, failure
):
    with closing(ResearchStore(tmp_path / "failure.db")) as store:
        if operation == "range":
            rid, page, candidate = create(store, interval=False)
            for _ in range(3):
                insert(store, rid, page, candidate.model_dump_json())
            alternate = page.model_copy(update={"id": page.id + "-alternate"})
            pid = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()[0]
            store.snapshot(rid, pid, alternate, "fixture")
            for _ in range(2):
                insert(store, rid, alternate, candidate.model_dump_json())
            original = store.load_snapshot
            calls = []

            def tracked(*args):
                calls.append(args)
                if len(calls) == 2:
                    raise failure("fixture")
                return original(*args)

            monkeypatch.setattr(store, "load_snapshot", tracked)

            def invoke():
                return ranges.saved_range_evidence(store, rid)
        else:
            rid, page, _ = batch(store)
            alternate = page.model_copy(update={"id": page.id + "-alternate"})
            pid = store.db.execute("SELECT id FROM pages WHERE run_id=?", (rid,)).fetchone()[0]
            store.snapshot(rid, pid, alternate, "fixture")
            with store.db:
                store.db.execute(
                    "UPDATE candidates SET snapshot_id=? WHERE id=(SELECT MAX(id) FROM candidates)",
                    (alternate.id,),
                )
            original = saved_evidence._validated_snapshot_payload
            calls = []

            def tracked(row):
                calls.append(row["snapshot_id"])
                if len(calls) == 2:
                    raise failure("fixture")
                return original(row)

            monkeypatch.setattr(saved_evidence, "_validated_snapshot_payload", tracked)

            def invoke():
                return store.evidence(rid)

        before = state(store)
        with pytest.raises(failure):
            invoke()
        assert len(invoke()) == (5 if operation == "range" else 3)
        assert len(calls) == 4
        assert state(store) == before


@pytest.mark.parametrize("mutation", ["field", "nested", "list"])
def test_evidence_batch_decodes_once_and_returns_independent_json(tmp_path, monkeypatch, mutation):
    with closing(ResearchStore(tmp_path / "evidence.db")) as store:
        rid, page, _ = batch(store)
        before = state(store)
        calls = tracked_decoder(monkeypatch)
        evidence = store.evidence(rid)
        assert len(evidence) == 3 and len(calls) == 1
        first = evidence[0]["snapshot"]
        if mutation == "field":
            first["url"] = "changed"
        elif mutation == "nested":
            first["sources"][0]["text"] = "changed"
        else:
            first["sources"].clear()
        assert all(item["snapshot"] == page.model_dump() for item in evidence[1:])
        assert all(item["snapshot"] == page.model_dump() for item in store.evidence(rid))
        assert len(calls) == 2
        assert state(store) == before


@pytest.mark.parametrize("damage", ["candidate", "record", "snapshot", "owner"])
def test_new_evidence_batch_revalidates_changed_ledger_and_every_record(
    tmp_path, monkeypatch, damage
):
    with closing(ResearchStore(tmp_path / "fresh.db")) as store:
        rid, page, _ = batch(store)
        calls = tracked_decoder(monkeypatch)
        assert len(store.evidence(rid)) == 3 and len(calls) == 1
        with store.db:
            if damage == "candidate":
                store.db.execute(
                    "UPDATE candidates SET payload='{}' WHERE id=(SELECT MAX(id) FROM candidates)"
                )
            elif damage == "record":
                store.db.execute(
                    "UPDATE records SET payload='{}' WHERE id=(SELECT MAX(id) FROM records)"
                )
            elif damage == "snapshot":
                store.db.execute("UPDATE snapshots SET payload='{}' WHERE id=?", (page.id,))
            else:
                other = store.create("Other", SCHEMA, TaskSpec(), None)
                store.db.execute("UPDATE pages SET run_id=? WHERE run_id=?", (other, rid))
        before = state(store)
        with pytest.raises(VerboisyError):
            store.evidence(rid)
        assert state(store) == before


def as_row(store, values):
    """Use real SQLite rows to exercise alternate historical batch representations."""
    names = list(values)
    return store.db.execute(
        "SELECT " + ",".join(f'? AS "{name}"' for name in names), [values[name] for name in names]
    ).fetchone()


@pytest.mark.parametrize("different", ["format", "omitted_defaults", "invalid", "duplicate"])
def test_same_reference_with_different_payload_never_inherits_validation(
    tmp_path, monkeypatch, different
):
    with closing(ResearchStore(tmp_path / "representations.db")) as store:
        rid, page, task = batch(store)
        evidence = store.evidence(rid)
        selected = store.db.execute(
            "SELECT * FROM records WHERE run_id=? ORDER BY id", (rid,)
        ).fetchall()
        rows = []
        for record, item in zip(selected, evidence, strict=True):
            rows.append(
                {
                    "stable_id": record["stable_id"],
                    "identity": record["identity"],
                    "record_payload": record["payload"],
                    "candidate_id": record["candidate_id"],
                    "run_id": rid,
                    "accepted": 1,
                    "payload": json.dumps(item["candidate"]),
                    "snapshot_id": page.id,
                    "snapshot_run_id": rid,
                    "page_run_id": rid,
                    "snapshot": page.model_dump_json(),
                }
            )
        rows[1]["snapshot"] = {
            "format": json.dumps(page.model_dump(), indent=2, sort_keys=True),
            "omitted_defaults": json.dumps(page.model_dump(exclude_defaults=True)),
            "invalid": "{}",
            "duplicate": page.model_dump_json()[:-1] + ',"id":"wrong"}',
        }[different]
        sqlite_rows = [as_row(store, values) for values in rows]
        calls = tracked_decoder(monkeypatch)
        before = state(store)
        if different in {"invalid", "duplicate"}:
            with pytest.raises(VerboisyError, match="Stored snapshot failed"):
                saved_evidence.decode_evidence_rows(
                    sqlite_rows, rid, task, encode=encode, lookup=lookup
                )
        else:
            decoded = saved_evidence.decode_evidence_rows(
                sqlite_rows, rid, task, encode=encode, lookup=lookup
            )
            assert decoded[1]["snapshot"] == json.loads(rows[1]["snapshot"])
            assert list(decoded[1]["snapshot"]) == list(json.loads(rows[1]["snapshot"]))
        assert len(calls) == 2
        assert state(store) == before


@pytest.mark.parametrize("operation", ["range", "evidence"])
@pytest.mark.parametrize("mutation", ["descriptor", "fields"])
def test_nested_projection_containers_remain_isolated(tmp_path, operation, mutation):
    from verboisy.evidence.models import ProjectionPlan

    with closing(ResearchStore(tmp_path / "projection.db")) as store:
        if operation == "range":
            rid, page, candidate = create(store, interval=False)
            for _ in range(3):
                insert(store, rid, page, candidate.model_dump_json())
        else:
            rid, page, _ = batch(store)
        projection = ProjectionPlan.model_validate(
            {
                "fields": [
                    {
                        "source": "/raw",
                        "target": "/weight",
                        "conversion": "number",
                        "descriptors": [{"kind": "definition", "source": "/descriptor"}],
                    }
                ]
            }
        )
        updated = page.model_copy(update={"dataset_projection": projection})
        with store.db:
            store.db.execute(
                "UPDATE snapshots SET payload=? WHERE id=?", (updated.model_dump_json(), page.id)
            )
        before = state(store)
        if operation == "range":
            result = ranges.saved_range_evidence(store, rid)
            first = result[0][0].dataset_projection
            if mutation == "descriptor":
                first.fields[0].descriptors[0].source = "/changed"
            else:
                first.fields.clear()
            assert all(item[0].dataset_projection == projection for item in result[1:])
        else:
            result = store.evidence(rid)
            first = result[0]["snapshot"]["dataset_projection"]
            if mutation == "descriptor":
                first["fields"][0]["descriptors"][0]["source"] = "/changed"
            else:
                first["fields"].clear()
            assert all(
                item["snapshot"]["dataset_projection"] == projection.model_dump()
                for item in result[1:]
            )
        assert state(store) == before
