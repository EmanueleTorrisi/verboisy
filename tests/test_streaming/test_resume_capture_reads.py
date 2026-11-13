# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Keep resume bounded without weakening saved-capture verification."""

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing

import pytest
from verboisy import StreamLedger, stream_dataset
from verboisy.streaming.contract import CHUNK_BYTES, StreamError
from verboisy.utils.config import Settings


@pytest.fixture
def paused_capture(tmp_path):
    source = tmp_path / "input.jsonl"
    database = tmp_path / "stream.db"
    text = "é" * (CHUNK_BYTES // 8)
    records = [{"ordinal": index, "text": text} for index in range(13)]
    with source.open("w", encoding="utf-8", newline="") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    config = Settings(_env_file=None, dataset_local_roots=[str(tmp_path)])
    result = stream_dataset(
        database=database,
        source=source,
        dataset_format="jsonl",
        config=config,
        rows_per_invocation=5,
    )
    assert (result.status, result.processed_rows) == ("PAUSED", 5)
    source.unlink()
    return database, config, result, records


def test_resume_does_not_reload_verified_prefix_chunks(paused_capture, monkeypatch):
    database, config, paused, records = paused_capture
    loads = Counter()
    initialize = StreamLedger.__init__

    def track_load(_cursor, values):
        if len(values) == 3 and isinstance(values[2], bytes):
            loads[values[0]] += 1
        return sqlite3.Row(_cursor, values)

    def observed(ledger, *args, **kwargs):
        initialize(ledger, *args, **kwargs)
        ledger.connection.row_factory = track_load

    with monkeypatch.context() as instrumentation:
        instrumentation.setattr(StreamLedger, "__init__", observed)
        resumed = stream_dataset(database=database, config=config, resume=paused.job_id)

    assert resumed.status == "COMPLETED"
    assert resumed.processed_rows == len(records)
    assert resumed.source_sha256 == paused.source_sha256
    # These chunks were loaded by the positioned parser before checking the
    # unread suffix. They should not have been fetched by another full scan.
    assert loads[0] == loads[1] == 1
    with closing(StreamLedger(database, read_only=True)) as ledger:
        assert [row["record"] for row in ledger.page(paused.job_id)] == records


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("bytes", "chunk integrity failure"),
        ("rehash", "aggregate integrity failure"),
        ("sequence", "chunk integrity failure"),
    ],
)
def test_resume_refuses_changed_unread_tail_before_writing(
    paused_capture, tmp_path, damage, expected
):
    database, config, paused, _records = paused_capture
    with closing(sqlite3.connect(database)) as db, db:
        seq, content, checksum = db.execute(
            "SELECT seq,content,sha256 FROM stream_chunks WHERE job_id=? ORDER BY seq DESC LIMIT 1",
            (paused.job_id,),
        ).fetchone()
        assert seq >= 2
        assert content.endswith(b"\n")
        changed = content[:-1] + b" "
        if damage == "sequence":
            # A noninteger sequence can sit between the last verified chunk and
            # the next expected integer in a non-strict SQLite table.
            db.execute(
                "INSERT INTO stream_chunks VALUES(?,?,?,?)",
                (paused.job_id, 1.5, hashlib.sha256(changed).hexdigest(), changed),
            )
        else:
            digest = hashlib.sha256(changed).hexdigest() if damage == "rehash" else checksum
            db.execute(
                "UPDATE stream_chunks SET content=?,sha256=? WHERE job_id=? AND seq=?",
                (changed, digest, paused.job_id, seq),
            )
    with closing(StreamLedger(database, read_only=True)) as ledger:
        checkpoint = ledger.job(paused.job_id)
    output = tmp_path / "result.json"
    with pytest.raises(StreamError, match=expected):
        stream_dataset(database=database, config=config, resume=paused.job_id, export=output)

    assert not list(tmp_path.glob("result.json*"))
    with closing(StreamLedger(database, read_only=True)) as ledger:
        assert ledger.job(paused.job_id) == checkpoint
        count = ledger.connection.execute(
            "SELECT COUNT(*) FROM stream_rows WHERE job_id=?", (paused.job_id,)
        ).fetchone()[0]
        assert count == paused.processed_rows
