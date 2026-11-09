# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Dataset quality is based on replayed, completed local snapshots."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

import pytest
from verboisy.evidence.models import ProjectionField, ProjectionPlan
from verboisy.streaming import StreamLedger, check_stream_quality, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.utils.config import Settings


def capture(root, filename, content, *, dataset_format="jsonl", **options):
    path = root / filename
    path.write_bytes(content)
    result = stream_dataset(
        database=root / "stream.db",
        source=path,
        dataset_format=dataset_format,
        config=Settings(_env_file=None, dataset_local_roots=[str(root)]),
        **options,
    )
    return path, result


def test_report_is_bound_to_verified_values_and_preserves_the_capture(tmp_path):
    data = (
        b'{"id":1,"label":"private example"}\n{"id":1,"label":null}\n'
        b'{"id":"1","label":"  "}\n{"id":2}\n'
    )
    source, job = capture(tmp_path, "input.jsonl", data)
    assert job.status == "COMPLETED"
    source.unlink()
    database = tmp_path / "stream.db"
    original = database.read_bytes()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    contract = {
        "version": "1",
        "min_rows": 4,
        "completeness": [{"field": "/label", "min_present_percent": 25}],
        "unique": [["/id"]],
    }
    args = {
        "database": database,
        "job_id": job.job_id,
        "contract": contract,
        "max_index_bytes": 65536,
        "scratch_dir": scratch,
    }
    report = check_stream_quality(**args)
    assert report == check_stream_quality(**args)
    assert report.source_sha256 == hashlib.sha256(data).hexdigest()
    assert report.source_bytes == len(data)
    assert report.job_id == job.job_id and report.rows == 4
    assert report.row_count.passed and not report.passed
    assert report.completeness[0].passed
    assert report.uniqueness[0].duplicates == 1
    assert report.uniqueness[0].examples[0].first_ordinal == 1
    assert "private example" not in json.dumps(asdict(report))
    assert database.read_bytes() == original
    assert not list(scratch.iterdir())


def test_quality_checks_follow_projected_columns(tmp_path):
    projection = ProjectionPlan(
        fields=[
            ProjectionField(source="/sku", target="/id"),
            ProjectionField(source="/value", target="/count", conversion="integer"),
        ]
    )
    _, job = capture(
        tmp_path,
        "input.csv",
        b"sku,value\n001,0\n002,1\n",
        dataset_format="csv",
        projection=projection,
    )
    assert job.status == "COMPLETED"
    report = check_stream_quality(
        database=tmp_path / "stream.db",
        job_id=job.job_id,
        contract={"version": "1", "completeness": [{"field": "/count"}], "unique": [["/id"]]},
    )
    assert report.passed and report.completeness[0].present == 2


def test_count_only_policy_can_explicitly_allow_a_header_only_table(tmp_path):
    _, job = capture(tmp_path, "empty.csv", b"id,label\n", dataset_format="csv")
    assert job.status == "COMPLETED"
    args = {"database": tmp_path / "stream.db", "job_id": job.job_id}
    rejected = check_stream_quality(**args, contract={"version": "1"})
    accepted = check_stream_quality(**args, contract={"version": "1", "min_rows": 0, "max_rows": 0})
    assert rejected.rows == accepted.rows == 0
    assert not rejected.passed and accepted.passed


@pytest.mark.parametrize("kind", ["paused", "opaque", "tampered"])
def test_unqualified_evidence_has_no_quality_report(tmp_path, kind):
    database = tmp_path / "stream.db"
    if kind == "opaque":
        _, job = capture(tmp_path, "data.bin", b"opaque", dataset_format="asset")
        assert job.status == "COMPLETED"
        message = "Opaque assets"
    elif kind == "paused":
        _, job = capture(tmp_path, "input.jsonl", b'{"id":1}\n{"id":2}\n', rows_per_invocation=1)
        assert job.status == "PAUSED"
        message = "completed streaming job"
    else:
        _, job = capture(tmp_path, "input.jsonl", b'{"id":1}\n{"id":2}\n')
        assert job.status == "COMPLETED"
        with closing(sqlite3.connect(database)) as db, db:
            db.execute(
                "UPDATE stream_rows SET source_json='{}' WHERE job_id=? AND ordinal=2",
                (job.job_id,),
            )
        message = "row evidence differs"
    original = database.read_bytes()
    with pytest.raises(StreamError, match=message):
        check_stream_quality(
            database=database, job_id=job.job_id, contract={"version": "1", "unique": [["/id"]]}
        )
    assert database.read_bytes() == original
    assert not list(tmp_path.glob(".verboisy-quality-*"))


def test_quality_check_refuses_an_inconsistent_read_transaction(tmp_path, monkeypatch):
    from verboisy.streaming import quality

    _, job = capture(tmp_path, "input.jsonl", b'{"id":1}\n')
    database = tmp_path / "stream.db"
    with closing(StreamLedger(database, read_only=True)) as ledger:
        ledger.connection.execute("BEGIN")
        monkeypatch.setattr(quality, "StreamLedger", lambda *_a, **_kw: ledger)
        with pytest.raises(StreamError, match="consistent streaming ledger snapshot"):
            check_stream_quality(database=database, job_id=job.job_id, contract={"version": "1"})
