# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Require verified local evidence before publishing incremental changes."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from verboisy.evidence.models import ProjectionField, ProjectionPlan
from verboisy.streaming import StreamLedger, UpdateLimits, stream_dataset, stream_updates
from verboisy.streaming.contract import StreamError
from verboisy.utils.config import Settings


def capture(root, filename, data, *, dataset_format="jsonl", **options):
    source = root / filename
    source.write_bytes(data)
    result = stream_dataset(
        database=root / "stream.db",
        source=source,
        dataset_format=dataset_format,
        config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
        **options,
    )
    return source, result


def params(root, before, after):
    return {
        "database": root / "stream.db",
        "baseline": before.job_id,
        "current": after.job_id,
        "keys": ("/id",),
        "output": root / "changes.jsonl",
    }


@pytest.fixture
def versions(tmp_path):
    _, before = capture(tmp_path, "old.jsonl", b'{"id":1,"name":"old"}\n{"id":2,"name":"keep"}\n')
    _, after = capture(tmp_path, "new.jsonl", b'{"id":1,"name":"new"}\n{"id":2,"name":"keep"}\n')
    assert before.status == after.status == "COMPLETED"
    return before, after


def test_export_replays_complete_captures_without_opening_original_sources(tmp_path):
    old = b'id,value\n001,"first\nline"\n002,unchanged\n003,retired\n'
    new = b'id,value\n002,unchanged\n001,"next\nline"\n004,new\n'
    old_path, before = capture(tmp_path, "old.csv", old, dataset_format="csv")
    new_path, after = capture(tmp_path, "new.csv", new, dataset_format="csv")
    assert before.status == after.status == "COMPLETED"
    old_path.unlink()
    new_path.unlink()
    args = params(tmp_path, before, after)
    db_before = args["database"].read_bytes()
    result = stream_updates(**args, complete_snapshot=True, limits=UpdateLimits(65536, 8192))
    header, updated, inserted, deleted, summary = map(
        json.loads, args["output"].read_bytes().splitlines()
    )
    assert header["baseline"]["source_sha256"] == hashlib.sha256(old).hexdigest()
    assert header["current"]["source_sha256"] == hashlib.sha256(new).hexdigest()
    assert updated["op"] == "update" and updated["row"] == {"id": "001", "value": "next\nline"}
    assert (updated["before"]["first_line"], updated["before"]["last_line"]) == (2, 3)
    assert (updated["after"]["first_line"], updated["after"]["last_line"]) == (3, 4)
    assert inserted["key"] == ["004"] and deleted["key"] == ["003"]
    assert summary["body_sha256"] == result.body_sha256
    assert (result.inserted, result.updated, result.removed, result.unchanged) == (1, 1, 1, 1)
    assert args["database"].read_bytes() == db_before


def test_keys_resolve_in_the_verified_projection(tmp_path):
    projection = ProjectionPlan(
        fields=[
            ProjectionField(source="/code", target="/id"),
            ProjectionField(source="/value", target="/count", conversion="integer"),
        ]
    )
    _, before = capture(
        tmp_path, "old.csv", b"code,value\n001,5\n", dataset_format="csv", projection=projection
    )
    _, after = capture(
        tmp_path, "new.csv", b"code,value\n001,7\n", dataset_format="csv", projection=projection
    )
    assert before.status == after.status == "COMPLETED"
    args = params(tmp_path, before, after)
    result = stream_updates(**args)
    assert result.updated == 1
    _, change, _ = map(json.loads, args["output"].read_bytes().splitlines())
    assert change["key"] == ["001"]
    assert change["row"] == {"id": "001", "count": 7}


@pytest.mark.parametrize("status", ["paused", "tampered"])
def test_partial_or_corrupt_current_job_never_publishes_a_patch(tmp_path, versions, status):
    before, after = versions
    if status == "paused":
        _, after = capture(
            tmp_path,
            "partial.jsonl",
            b'{"id":1,"name":"new"}\n{"id":2,"name":"keep"}\n',
            rows_per_invocation=1,
        )
        assert after.status == "PAUSED"
        message = "completed jobs"
    else:
        with closing(sqlite3.connect(tmp_path / "stream.db")) as db, db:
            db.execute(
                "UPDATE stream_rows SET source_json='{}' WHERE job_id=? AND ordinal=2",
                (after.job_id,),
            )
        message = "row evidence differs"
    args = params(tmp_path, before, after)
    fingerprint = args["database"].read_bytes()
    with pytest.raises(StreamError, match=message):
        stream_updates(**args, complete_snapshot=True)
    assert not args["output"].exists()
    assert args["database"].read_bytes() == fingerprint


def test_incompatible_or_opaque_jobs_do_not_define_a_delta(tmp_path, versions):
    before, _ = versions
    _, incompatible = capture(tmp_path, "table.csv", b"id,name\n1,new\n", dataset_format="csv")
    _, opaque = capture(tmp_path, "opaque.bin", b"opaque", dataset_format="asset")
    assert incompatible.status == opaque.status == "COMPLETED"
    for other, reason in ((incompatible, "share a format"), (opaque, "Opaque asset")):
        args = params(tmp_path, before, other)
        with pytest.raises(StreamError, match=reason):
            stream_updates(**args)
        assert not args["output"].exists()


def test_destination_cannot_replace_a_source_or_an_existing_output(tmp_path, versions):
    before, after = versions
    args = params(tmp_path, before, after)
    previous = args["output"]
    previous.write_bytes(b"previous generation")
    with pytest.raises(StreamError, match="new .jsonl"):
        stream_updates(**args)
    assert previous.read_bytes() == b"previous generation"
    args["output"] = tmp_path / "wrong.csv"
    with pytest.raises(StreamError, match="new .jsonl"):
        stream_updates(**args)
    source = tmp_path / "old.jsonl"
    source.unlink()
    args["output"] = source
    with pytest.raises(StreamError, match="protected"):
        stream_updates(**args)
    assert not source.exists()


def test_job_identity_and_completion_confirmation_are_explicit(tmp_path, versions):
    before, after = versions
    args = params(tmp_path, before, before)
    with pytest.raises(StreamError, match="distinct"):
        stream_updates(**args)
    args["current"] = after.job_id
    with pytest.raises(StreamError, match="explicit boolean"):
        stream_updates(**args, complete_snapshot=1)


def test_cannot_start_from_an_already_open_read_transaction(tmp_path, versions, monkeypatch):
    from verboisy.streaming import update

    args = params(tmp_path, *versions)
    with closing(StreamLedger(args["database"], read_only=True)) as ledger:
        ledger.connection.execute("BEGIN")
        monkeypatch.setattr(update, "StreamLedger", lambda *_a, **_kw: ledger)
        with pytest.raises(StreamError, match="consistent streaming ledger snapshot"):
            stream_updates(**args)
    assert not args["output"].exists()
