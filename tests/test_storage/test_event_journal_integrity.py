# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Journal preflight preserves the previous export generation and saved ledger."""

import hashlib
import json
from contextlib import closing

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.storage.dataset import export_dataset
from verboisy.storage.proof import export_proof
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_admission_transactions import SCHEMA, capture
from tests.test_storage.test_evidence_run_scope import evidence_state


def selected_run(store):
    task = TaskSpec(identity_fields=["/name"])
    rid = store.create("People", SCHEMA, task, None)
    page, candidate = capture(store, rid, 31)
    store.accept(rid, page, candidate, [], task)
    return rid, task


def existing_generation(destination):
    paths = [
        destination,
        destination.with_suffix(destination.suffix + ".manifest.json"),
        destination.with_suffix(destination.suffix + ".evidence.json"),
        destination.with_suffix(destination.suffix + ".events.json"),
        destination.with_name(destination.stem + ".proof.txt"),
    ]
    for path in paths:
        path.write_bytes(b"previous complete generation")
    return paths


@pytest.mark.parametrize("extension", ["json", "csv"])
@pytest.mark.parametrize("operation", ["events", "filtered", "proof", "dataset", "custom_rows"])
@pytest.mark.parametrize(
    "payload",
    [
        "PRIVATE_INVALID_JSON",
        '{"x":1,"x":2}',
        '{"nested":{"x":1,"x":2}}',
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        '{"nested":[1e999]}',
    ],
)
def test_invalid_json_fails_before_publication_after_read_only_reopen(
    tmp_path, extension, operation, payload
):
    database = tmp_path / "journal.db"
    destination = tmp_path / ("rows." + extension)
    artifacts = existing_generation(destination)
    with closing(ResearchStore(database)) as writer:
        rid, task = selected_run(writer)
        with writer.db:
            writer.db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)",
                (rid, "custom_event", payload),
            )
        before = evidence_state(writer)
    with closing(ResearchStore(database, read_only=True)) as reader:
        with pytest.raises(VerboisyError, match="Saved event payload failed integrity") as caught:
            if operation in {"events", "filtered"}:
                reader.events(rid, "custom_event" if operation == "filtered" else None)
            elif operation == "proof":
                export_proof(reader, rid, destination)
            else:
                export_dataset(
                    reader,
                    rid,
                    destination,
                    SCHEMA,
                    task,
                    rows=[{"id": 1, "name": "Alice", "age": 31}]
                    if operation == "custom_rows"
                    else None,
                )
        assert "PRIVATE" not in str(caught.value)
        assert evidence_state(reader) == before
    assert all(path.read_bytes() == b"previous complete generation" for path in artifacts)


@pytest.mark.parametrize("extension", ["json", "csv"])
@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("payload", ["[]", "null", '"reserved"'])
def test_nonobject_search_payload_fails_before_export_replacement(
    tmp_path, extension, custom, payload
):
    destination = tmp_path / ("rows." + extension)
    artifacts = existing_generation(destination)
    with closing(ResearchStore(tmp_path / "search.db")) as store:
        rid, task = selected_run(store)
        with store.db:
            store.db.execute(
                "INSERT INTO events(run_id,kind,payload) VALUES(?,?,?)",
                (rid, "search_request", payload),
            )
        before = evidence_state(store)
        with pytest.raises(ValueError, match="search request payload must be an object"):
            store.search_attempt_count(rid)
        with pytest.raises(ValueError, match="search request payload must be an object"):
            export_dataset(
                store,
                rid,
                destination,
                SCHEMA,
                task,
                rows=[{"id": 1, "name": "Alice", "age": 31}] if custom else None,
            )
        assert evidence_state(store) == before
    assert all(path.read_bytes() == b"previous complete generation" for path in artifacts)


@pytest.mark.parametrize("extension", ["json", "csv"])
@pytest.mark.parametrize(
    "payload",
    [None, [], "Unicode: è", 2**80, [1.25, -0.0], {"nested": [True, False, {"label": "è"}]}],
)
def test_valid_historical_json_and_accounting_survive_export(tmp_path, extension, payload):
    with closing(ResearchStore(tmp_path / "valid.db")) as store:
        rid, task = selected_run(store)
        store.event(rid, "custom_event", payload)
        store.event(rid, "run_config", {"model": "fixture"})
        for value in [
            {"provider": "openai", "status": "reserved", "attempt_id": "a"},
            {"provider": "openai", "status": "reserved", "attempt_id": "a"},
            {"provider": "openai", "status": "completed", "attempt_id": "a"},
            {"provider": "brave", "status": "reserved", "attempt_id": "b"},
            {"provider": "brave", "status": "blocked", "attempt_id": "c"},
            {"provider": "brave", "status": "reserved", "attempt_id": None},
        ]:
            store.event(rid, "search_request", value)
        other = store.create("Other", SCHEMA, task, None)
        store.event(other, "search_request", {"status": "reserved", "attempt_id": "foreign"})
        before = evidence_state(store)
        expected = store.events(rid)
        assert store.events(rid, "custom_event")[0]["payload"] == payload
        assert store.search_attempt_count(rid) == 2
        destination = tmp_path / ("rows." + extension)
        manifest = json.loads(export_dataset(store, rid, destination, SCHEMA, task).read_text())
        journal = json.loads(
            destination.with_suffix(destination.suffix + ".events.json").read_text()
        )
        assert journal["events"] == expected
        assert manifest["search_attempts_reserved"] == {"openai": 1, "brave": 1}
        assert manifest["model_invocations"] == [{"model": "fixture"}]
        for name, digest in manifest["files"].items():
            assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
        assert evidence_state(store) == before
