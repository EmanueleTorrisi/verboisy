# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real SQLite tampering is rejected before resume can alter damaged history."""

import json
import sqlite3
from contextlib import closing

import pytest
from verboisy.streaming import StreamLedger, stream_dataset
from verboisy.streaming.contract import StreamError

from tests.test_streaming.test_streaming import prepare as _prepare_fixture

prepare = _prepare_fixture


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE stream_jobs SET processed=99",
        'UPDATE stream_rows SET output_json=\'{"name":"forged"}\'',
        "UPDATE stream_rows SET source_json='{}'",
        "UPDATE stream_rows SET first_line=999",
        "UPDATE stream_rows SET ordinal=9",
        "UPDATE stream_jobs SET status='UNKNOWN'",
        "UPDATE stream_jobs SET captured=2",
        "UPDATE stream_jobs SET byte_count=-1",
        "UPDATE stream_jobs SET sha256='wrong'",
        "UPDATE stream_chunks SET content=x'00'",
        "UPDATE stream_jobs SET status='COMPLETED'",
        'UPDATE stream_jobs SET contract=\'{"version":"1","version":"1"}\'',
    ],
)
def test_damaged_prefix_is_preserved(prepare, tmp_path, sql):
    result = prepare(rows_per_invocation=1)
    dbpath = tmp_path / "stream.db"
    with sqlite3.connect(dbpath) as db:
        db.execute(sql)
    with closing(StreamLedger(dbpath, read_only=True)) as ledger:
        before = ledger.connection.iterdump()
        before = list(before)
        with pytest.raises(StreamError):
            ledger.page(result.job_id)
    with pytest.raises(StreamError):
        stream_dataset(database=dbpath, resume=result.job_id)
    with sqlite3.connect(dbpath) as db:
        assert list(db.iterdump()) == before


def test_valid_prefix_resumes_without_original_source(prepare, tmp_path):
    result = prepare(rows_per_invocation=1)
    (tmp_path / "input").unlink()
    resumed = stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    assert resumed.status == "COMPLETED" and resumed.processed_rows == 2


@pytest.mark.parametrize(
    "update",
    [
        {"version": "2"},
        {"limits": {"max_rows": True}},
        {"csv_mode": "guess"},
        {"protected_inputs": ["relative"]},
        {"source_uri": "https://private.invalid/"},
        {"format": "json"},
        {"schema": None},
    ],
)
def test_saved_contract_validation_before_status_mutation(prepare, tmp_path, update):
    result = prepare(rows_per_invocation=1)
    with sqlite3.connect(tmp_path / "stream.db") as db:
        contract = json.loads(db.execute("SELECT contract FROM stream_jobs").fetchone()[0])
        contract.update(update)
        db.execute("UPDATE stream_jobs SET contract=?", (json.dumps(contract),))
    with pytest.raises(StreamError):
        stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    with sqlite3.connect(tmp_path / "stream.db") as db:
        assert db.execute("SELECT status FROM stream_jobs").fetchone()[0] == "PAUSED"


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE stream_rows SET source_json='[]'",
        "UPDATE stream_jobs SET captured=0,status='COMPLETED'",
        "UPDATE stream_jobs SET contract=json_set(contract,'$.limits',null)",
    ],
)
def test_additional_saved_shapes_fail(prepare, tmp_path, mutation):
    result = prepare()
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute(mutation)
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, pytest.raises(StreamError):
        ledger.page(result.job_id)


def test_source_prefix_cannot_extend_beyond_capture(prepare, tmp_path):
    result = prepare()
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute(
            "INSERT INTO stream_rows SELECT job_id,3,first_line,last_line,source_json,output_json "
            "FROM stream_rows WHERE ordinal=2"
        )
        writer.execute("UPDATE stream_jobs SET processed=3")
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="exceeds"),
    ):
        ledger.page(result.job_id)


@pytest.mark.parametrize("method", ["job", "jobs", "page"])
def test_public_sql_failures_are_stream_errors(prepare, tmp_path, method):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        ledger.connection.execute("PRAGMA foreign_keys=OFF")
        if method == "page":
            with ledger.connection:
                ledger.connection.execute("DROP TABLE stream_rows")
        else:
            with ledger.connection:
                ledger.connection.execute("DROP TABLE stream_jobs")
        with pytest.raises(StreamError):
            ledger.jobs() if method == "jobs" else getattr(ledger, method)(result.job_id)


@pytest.mark.parametrize("column", ["source_json", "output_json"])
def test_oversized_saved_values_rejected_under_record_ceiling(prepare, tmp_path, column):
    result = prepare()
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute(f"UPDATE stream_rows SET {column}=?", ('"' + "x" * 1_048_577 + '"',))
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, pytest.raises(StreamError):
        ledger.page(result.job_id)


def test_incomplete_completed_checkpoint_cannot_replace_old_export(prepare, tmp_path):
    from verboisy.streaming.export import export_stream

    result = prepare(rows_per_invocation=1)
    destination = tmp_path / "rows.json"
    destination.write_text("old")
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute("UPDATE stream_jobs SET status='COMPLETED'")
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, pytest.raises(StreamError):
        export_stream(ledger, ledger.job(result.job_id), destination)
    assert destination.read_text() == "old"


def test_partial_tables_and_wrong_primary_key_fail_without_repair(prepare, tmp_path):
    prepare()
    path = tmp_path / "stream.db"
    with sqlite3.connect(path) as writer:
        writer.execute("ALTER TABLE stream_rows DROP COLUMN source_json")
    before = path.read_bytes()
    with pytest.raises(StreamError, match="schema"):
        StreamLedger(path)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as writer:
        writer.execute("DROP TABLE stream_rows")
        writer.execute(
            "CREATE TABLE stream_rows(job_id TEXT,ordinal INTEGER,"
            "first_line INTEGER,last_line INTEGER,"
            "source_json TEXT,output_json TEXT)"
        )
    before = path.read_bytes()
    with pytest.raises(StreamError, match="primary key"):
        StreamLedger(path)
    assert path.read_bytes() == before


def test_public_page_cannot_replay_an_unfinished_capture(prepare, tmp_path):
    result = prepare()
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute("DELETE FROM stream_rows")
        writer.execute(
            "UPDATE stream_jobs SET captured=0,processed=0,byte_count=0,sha256=NULL,status='PAUSED'"
        )
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="incomplete capture"),
    ):
        ledger.page(result.job_id)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE stream_jobs SET contract=json_set(contract,'$.source_uri',1)",
        "UPDATE stream_chunks SET content='text'",
        "UPDATE stream_chunks SET content=zeroblob(1048577)",
    ],
)
def test_typed_source_contract_and_bounded_chunks(prepare, tmp_path, mutation):
    result = prepare()
    with sqlite3.connect(tmp_path / "stream.db") as writer:
        writer.execute(mutation)
    with pytest.raises(StreamError):
        stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)


def test_paging_sql_snapshot_failure_is_a_safe_stream_error(prepare, tmp_path, monkeypatch):
    result = prepare()

    def fail_read(*_args):
        raise sqlite3.OperationalError("snapshot unavailable")

    monkeypatch.setattr("verboisy.streaming.integrity.read_verified_page", fail_read)
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="Cannot read verified streaming page"),
    ):
        ledger.page(result.job_id)


def test_verified_export_iterator_rejects_paused_job(prepare, tmp_path):
    from verboisy.streaming.integrity import verified_export_rows

    result = prepare(rows_per_invocation=1)
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="Only completed"),
    ):
        list(verified_export_rows(ledger, ledger.job(result.job_id)))


@pytest.mark.parametrize("fault", ["short_capture", "decoder"])
def test_export_replay_fault_preserves_prior_published_bytes(prepare, tmp_path, monkeypatch, fault):
    from verboisy.streaming.export import export_stream

    result = prepare()
    target = tmp_path / "prior.jsonl"
    target.write_text("prior generation")
    if fault == "short_capture":
        monkeypatch.setattr(
            "verboisy.streaming.integrity.captured_rows", lambda *_args: (row for row in ())
        )
        expected = "source EOF"
    else:

        def fail_decode(*_args):
            raise ValueError("invalid saved decoder output")

        monkeypatch.setattr("verboisy.streaming.integrity._verify_row", fail_decode)
        expected = "Cannot verify streaming export evidence"
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match=expected),
    ):
        export_stream(ledger, ledger.job(result.job_id), target)
    assert target.read_text() == "prior generation"
    assert not target.with_name(target.name + ".manifest.json").exists()
