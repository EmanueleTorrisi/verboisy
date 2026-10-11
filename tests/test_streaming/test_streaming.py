# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Streaming contracts, immutable capture, checkpoints and portable export integrity."""

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import parse_dataset
from verboisy.streaming import StreamLedger, StreamLimits, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.streaming.export import export_stream
from verboisy.utils.config import Settings


@pytest.fixture(autouse=True)
def no_external_work():
    with (
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            new=AsyncMock(side_effect=AssertionError("model")),
        ),
        patch("verboisy.api.web_search", new=AsyncMock(side_effect=AssertionError("search"))),
        patch(
            "verboisy.browser.context.BrowserManager.start",
            new=AsyncMock(side_effect=AssertionError("browser")),
        ),
    ):
        yield


@pytest.fixture
def prepare(tmp_path):
    default_raw = '{"name":"Anaïs"}\n{"name":"Bob"}\n'.encode()

    def invoke(raw=default_raw, fmt="jsonl", **kwargs):
        source = tmp_path / "input"
        source.write_bytes(raw)
        return stream_dataset(
            database=tmp_path / "stream.db",
            source=source,
            dataset_format=fmt,
            config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
            **kwargs,
        )

    return invoke


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", 'name,note\r\nAnaïs,"one\ntwo"\r\nBob,=1+1\r\n'),
        ("tsv", 'name\tnote\nAnaïs\t"one\ntwo"\nBob\t=1+1\n'),
        ("jsonl", '\n{"name":"Anaïs","note":1}\n{"name":"Bob","note":null}\n'),
        ("text", "Anaïs\r\n\r\nBob"),
        ("asset", "binary\x00\xff"),
    ],
)
def test_parity_paging_export_and_resume_after_source_removal(prepare, tmp_path, fmt, body):
    raw = body.encode("latin1") if fmt == "asset" else body.encode()
    baseline = parse_dataset(raw, fmt)
    first = prepare(raw, fmt, rows_per_invocation=1)
    assert first.status == "PAUSED" and first.processed_rows == 1
    (tmp_path / "input").unlink()
    result = stream_dataset(
        database=tmp_path / "stream.db", resume=first.job_id, export=tmp_path / "rows.json"
    )
    assert result.status == "COMPLETED" and result.processed_rows == len(baseline.rows)
    assert (
        result.input_bytes == len(raw) and result.source_sha256 == hashlib.sha256(raw).hexdigest()
    )
    expected = [row.values for row in baseline.rows]
    assert json.loads((tmp_path / "rows.json").read_text(encoding="utf-8")) == expected
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert [row["record"] for row in ledger.page(result.job_id)] == expected
        assert ledger.page(result.job_id, after=1, limit=1) == (
            [{"ordinal": 2, "record": expected[1]}] if len(expected) > 1 else []
        )
        job = ledger.job(result.job_id)
        assert job["processed"] == len(expected)
    manifest = json.loads((tmp_path / "rows.json.manifest.json").read_text(encoding="utf-8"))
    assert not manifest["truth_verified"] and not manifest["global_completeness_claimed"]
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    assert (tmp_path / "rows.json.source.bin").read_bytes() == raw
    proofs = [
        json.loads(line)
        for line in (tmp_path / "rows.json.evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [p["source_values"] for p in proofs] == expected
    assert [p["line_start"] for p in proofs] == [r.line_start for r in baseline.rows]
    assert len({p["record_id"] for p in proofs}) == len(expected)
    again = stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    assert again == result


@pytest.mark.parametrize("suffix", ["csv", "jsonl", "json"])
def test_projection_and_export_shapes(prepare, tmp_path, suffix):
    plan = ProjectionPlan(fields=[{"source": "/n", "target": "/number", "conversion": "integer"}])
    result = prepare(
        b'{"n":"12"}\n',
        projection=plan,
        schema={"number": {"type": "integer"}},
        export=tmp_path / f"rows.{suffix}",
    )
    assert result.status == "COMPLETED"
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert ledger.page(result.job_id) == [{"ordinal": 1, "record": {"number": 12}}]
    proofs = json.loads((tmp_path / f"rows.{suffix}.evidence.jsonl").read_text(encoding="utf-8"))
    assert proofs["output_values"] == {"number": 12} and not proofs["output_is_source"]
    if suffix == "csv":
        assert list(
            csv.reader(io.StringIO((tmp_path / "rows.csv").read_text(encoding="utf-8")))
        ) == [
            ["number"],
            ["12"],
        ]
    elif suffix == "jsonl":
        assert json.loads((tmp_path / "rows.jsonl").read_text(encoding="utf-8")) == {"number": 12}
    else:
        assert json.loads((tmp_path / "rows.json").read_text(encoding="utf-8")) == [{"number": 12}]


@pytest.mark.parametrize(
    "raw,fmt",
    [
        (b"", "csv"),
        (b"", "text"),
        (b"\n", "jsonl"),
        (b"<html>", "csv"),
        (b"a,a\n1,2", "csv"),
        (b" ,b\n1,2", "csv"),
        (b"a,b\n1", "csv"),
        (b'a\n"bad', "csv"),
        (b"\xff", "text"),
        (b"42\n", "jsonl"),
        (b'{"n":NaN}\n', "jsonl"),
    ],
)
def test_malformed_inputs_have_no_admitted_rows(prepare, raw, fmt):
    result = prepare(raw, fmt)
    assert result.status == "FAILED" and result.processed_rows == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_input_bytes", 0),
        ("max_rows", True),
        ("max_record_bytes", "1"),
        ("max_storage_bytes", 100),
        ("max_record_bytes", 16_777_217),
    ],
)
def test_limits_reject_invalid_values(field, value):
    with pytest.raises(StreamError):
        StreamLimits(**{field: value})


@pytest.mark.parametrize("budget", [0, -1, True, "1"])
def test_invalid_invocation_budget_precedes_capture(prepare, budget):
    with pytest.raises(StreamError, match="budget"):
        prepare(rows_per_invocation=budget)


@pytest.mark.parametrize("fmt", ["json", "docx", "xlsx", "pdf", None])
def test_nonstreaming_formats_are_explicit(prepare, fmt):
    with pytest.raises(StreamError, match="format"):
        prepare(fmt=fmt)


def test_empty_binary_capture_and_header_only_table(prepare, tmp_path):
    for fmt, raw in [("asset", b""), ("csv", b"name\n")]:
        result = prepare(raw, fmt)
        assert result.status == "COMPLETED"
        assert result.processed_rows == (1 if fmt == "asset" else 0)
    result = stream_dataset(
        database=tmp_path / "stream.db", resume=result.job_id, export=tmp_path / "empty.json"
    )
    assert json.loads((tmp_path / "empty.json").read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "body,fmt,ceiling",
    [
        (b"abcdefghij", "text", 5),
        (b'a\n"ab\ncd\nef"', "csv", 7),
        (b'a\n""""""', "csv", 8),
        (b"\xc3\xa9\xc3\xa9\n", "text", 4),
    ],
)
def test_physical_and_decoded_record_limits(prepare, body, fmt, ceiling):
    result = prepare(body, fmt, limits=StreamLimits(max_record_bytes=ceiling))
    assert result.status == "FAILED" and "record byte limit" in result.reason


def test_input_and_row_limits_are_enforced(prepare):
    assert prepare(limits=StreamLimits(max_input_bytes=1)).status == "FAILED"
    result = prepare(limits=StreamLimits(max_rows=1))
    assert result.status == "FAILED" and result.processed_rows == 0


def test_array_schema_uses_row_validator(prepare):
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    }
    assert prepare(schema=schema).status == "COMPLETED"
    assert prepare(b'{"name":12}\n', schema=schema).status == "FAILED"


def test_resume_contract_is_fixed_and_unknown_job_is_rejected(prepare, tmp_path):
    result = prepare(rows_per_invocation=1)
    with pytest.raises(StreamError, match="saved"):
        stream_dataset(database=tmp_path / "stream.db", resume=result.job_id, schema={})
    with pytest.raises(StreamError, match="No saved"):
        stream_dataset(database=tmp_path / "stream.db", resume="missing")


def test_source_grants_and_ledger_aliases(tmp_path):
    source = tmp_path / "input"
    source.write_text("a\n1", encoding="utf-8")
    result = stream_dataset(
        database=tmp_path / "stream.db",
        source=source,
        dataset_format="csv",
        config=Settings(_env_file=None),
    )
    assert result.status == "FAILED" and "DATASET_LOCAL_ROOTS" in result.reason
    with pytest.raises(StreamError, match="ledger"):
        stream_dataset(database=source, source=source, dataset_format="csv")


@pytest.mark.parametrize(
    "after,limit", [(-1, 1), (True, 1), (0, 0), (0, 1001), (0, True), (0, "1")]
)
def test_bounded_pages(prepare, tmp_path, after, limit):
    result = prepare()
    with (
        closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger,
        pytest.raises(StreamError, match="Page"),
    ):
        ledger.page(result.job_id, after=after, limit=limit)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE stream_chunks SET content=x'00'",
        "UPDATE stream_chunks SET seq=100",
        "UPDATE stream_chunks SET sha256='wrong'",
        "UPDATE stream_chunks SET content=x''",
        "UPDATE stream_jobs SET byte_count=999",
        "UPDATE stream_jobs SET sha256='wrong'",
    ],
)
def test_corruption_blocks_resume_and_export(prepare, tmp_path, mutation):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, ledger.connection:
        ledger.connection.execute(mutation)
    resumed = stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    assert resumed.status == "FAILED" and "integrity" in resumed.reason
    assert not (tmp_path / "rows.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE stream_rows SET source_json='{}'",
        "UPDATE stream_rows SET first_line=99",
        "UPDATE stream_rows SET output_json='{}'",
        "DELETE FROM stream_rows",
        "UPDATE stream_jobs SET processed=99",
    ],
)
def test_row_tampering_cannot_publish_a_manifest(prepare, tmp_path, mutation):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, ledger.connection:
        ledger.connection.execute(mutation)
        with pytest.raises(StreamError, match="row"):
            export_stream(ledger, ledger.job(result.job_id), tmp_path / "rows.jsonl")
    assert not (tmp_path / "rows.jsonl.manifest.json").exists()


def test_checkpoint_commit_and_rollback_on_interruption(prepare, tmp_path, monkeypatch):
    import verboisy.streaming.api as api

    original = api._commit
    calls = 0

    def interrupt(ledger, job_id, batch):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        original(ledger, job_id, batch)

    monkeypatch.setattr(api, "_commit", interrupt)
    raw = b'{"x":1}\n' * 1200
    first = prepare(raw)
    assert (
        first.status == "PAUSED" and first.processed_rows == 512 and first.reason == "interrupted"
    )
    monkeypatch.setattr(api, "_commit", original)
    (tmp_path / "input").unlink()
    second = stream_dataset(database=tmp_path / "stream.db", resume=first.job_id)
    assert second.status == "COMPLETED" and second.processed_rows == 1200
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert ledger.connection.execute("SELECT COUNT(*) FROM stream_rows").fetchone()[0] == 1200


def test_partial_capture_requires_reacquisition_without_admitted_rows(tmp_path):
    import verboisy.streaming.capture as capture

    source = tmp_path / "input"
    raw = b"x" * 2_000_000
    source.write_bytes(raw)
    expected = source.stat()

    class Broken(io.BytesIO):
        def fileno(self):
            return 7

        def read(self, *_args):
            if self.tell():
                raise KeyboardInterrupt
            return super().read(1_048_576)

    config = Settings(_env_file=None, dataset_local_roots=[str(tmp_path)])
    with (
        patch.object(Path, "open", return_value=Broken(raw)),
        patch.object(capture.os, "fstat", return_value=expected),
    ):
        first = stream_dataset(
            database=tmp_path / "stream.db", source=source, dataset_format="asset", config=config
        )
    assert first.status == "PAUSED" and first.processed_rows == 0
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert not ledger.job(first.job_id)["captured"]
        assert ledger.connection.execute("SELECT COUNT(*) FROM stream_chunks").fetchone()[0] == 1
    assert (
        stream_dataset(database=tmp_path / "stream.db", resume=first.job_id, config=config).status
        == "COMPLETED"
    )


def test_sqlite_disk_limit_is_resumable(prepare, tmp_path):
    result = prepare(
        b'{"pad":"' + b"x" * 100_000 + b'"}\n', limits=StreamLimits(max_storage_bytes=65_536)
    )
    assert result.status == "PAUSED" and result.reason == "storage_error"
    # The configured ceiling is a database-wide page limit, not a RAM allocation.
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert (
            ledger.connection.execute("PRAGMA page_count").fetchone()[0]
            * ledger.connection.execute("PRAGMA page_size").fetchone()[0]
            <= 65_536
        )


@pytest.mark.parametrize("suffix", ["pdf", "xlsx"])
def test_unsupported_export(prepare, tmp_path, suffix):
    result = prepare()
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="export"),
    ):
        export_stream(ledger, ledger.job(result.job_id), tmp_path / f"rows.{suffix}")


def test_export_refuses_incomplete_jobs_and_protected_paths(prepare, tmp_path):
    result = prepare(rows_per_invocation=1)
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="completed"),
    ):
        export_stream(ledger, ledger.job(result.job_id), tmp_path / "rows.json")
    result = stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    for target in [tmp_path / "input", tmp_path / "stream.db"]:
        target_json = target.with_suffix(".json")
        target_json.mkdir()
        with (
            closing(StreamLedger(tmp_path / "stream.db")) as ledger,
            pytest.raises(StreamError, match="unsafe"),
        ):
            export_stream(ledger, ledger.job(result.job_id), target_json)


@pytest.mark.parametrize("raw", [b'{"x":{}}\n', b'{"x":1}\n{"y":2}\n'])
def test_csv_rejects_nested_or_unstable_columns(prepare, tmp_path, raw):
    result = prepare(raw)
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="flat"),
    ):
        export_stream(ledger, ledger.job(result.job_id), tmp_path / "rows.csv")


def test_failed_publish_removes_stale_manifest(prepare, tmp_path, monkeypatch):
    result = prepare(export=tmp_path / "rows.jsonl")
    original = Path.replace

    def fail(path, target):
        if path.name.endswith(".source.bin"):
            raise OSError("disk unavailable")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail)
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger, pytest.raises(OSError):
        export_stream(ledger, ledger.job(result.job_id), tmp_path / "rows.jsonl")
    assert not (tmp_path / "rows.jsonl.manifest.json").exists()


def test_ledger_versions_locks_and_read_only(tmp_path, prepare):
    with pytest.raises(StreamError, match="existing"):
        StreamLedger(tmp_path / "missing", read_only=True)
    blank = tmp_path / "empty"
    sqlite3.connect(blank).close()
    with pytest.raises(StreamError, match="streaming ledger"):
        StreamLedger(blank, read_only=True)
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as writer:
        with pytest.raises(StreamError, match="in use"):
            StreamLedger(tmp_path / "stream.db")
        with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as reader:
            assert reader.job(result.job_id) == writer.job(result.job_id)
        with writer.connection:
            writer.connection.execute("UPDATE stream_meta SET version=999")
    with pytest.raises(StreamError, match="version"):
        StreamLedger(tmp_path / "stream.db")
    ledger = StreamLedger(tmp_path / "other")
    ledger.close()
    ledger.close()
    with pytest.raises(StreamError, match="closed"):
        _ = ledger.connection


def test_cli_new_job_resume_and_invalid_configuration(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.write_text('{"x":1}\n{"x":2}\n', encoding="utf-8")
    monkeypatch.setattr(
        "verboisy.cli.streaming.Settings",
        lambda: Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    cli = CliRunner()
    base = ["stream", "--database", str(tmp_path / "stream.db")]
    first = cli.invoke(
        app, [*base, "--dataset-file", f"jsonl={source}", "--rows-per-invocation", "1"]
    )
    assert first.exit_code == 0, first.output
    job = json.loads(first.output)["job_id"]
    source.unlink()
    second = cli.invoke(app, [*base, "--resume", job, "--export", str(tmp_path / "rows.jsonl")])
    assert second.exit_code == 0 and json.loads(second.output)["processed_rows"] == 2
    assert cli.invoke(app, [*base, "--resume", job, "--max-rows", "1"]).exit_code == 1
    assert cli.invoke(app, [*base, "--dataset-file", "unknown=x"]).exit_code == 1
    assert cli.invoke(app, [*base, "--schema", str(tmp_path / "missing")]).exit_code == 1


def test_byte_bounded_batches_do_not_wait_for_512_large_rows(prepare):
    raw = (b'{"pad":"' + b"x" * 500_000 + b'"}\n') * 20
    result = prepare(raw)
    assert result.status == "COMPLETED" and result.processed_rows == 20


def test_nul_and_excessive_headers_are_rejected(prepare):
    assert prepare(b"a\x00b", "text").status == "FAILED"
    assert prepare(",".join(f"h{i}" for i in range(1001)).encode(), "csv").status == "FAILED"


def test_local_change_and_non_regular_source_guards(tmp_path, monkeypatch):
    import verboisy.streaming.capture as capture

    source = tmp_path / "input"
    source.write_bytes(b"abc")
    config = Settings(_env_file=None, dataset_local_roots=[str(tmp_path)])
    result = stream_dataset(
        database=tmp_path / "stream.db", source=tmp_path, dataset_format="asset", config=config
    )
    assert result.status == "FAILED" and "regular file" in result.reason
    old = source.stat()
    with patch.object(capture.os, "fstat", return_value=tmp_path.stat()):
        result = stream_dataset(
            database=tmp_path / "stream.db", source=source, dataset_format="asset", config=config
        )
    assert result.status == "FAILED" and "before capture" in result.reason
    attrs = list(old)
    attrs[6] = 1
    with patch.object(capture.os, "fstat", return_value=type(old)(attrs)):
        result = stream_dataset(
            database=tmp_path / "stream.db", source=source, dataset_format="asset", config=config
        )
    assert result.status == "FAILED" and "during capture" in result.reason


def test_ledger_rejects_aliases_bad_storage_and_unrelated_databases(tmp_path, prepare):
    prepare()
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "stream.db")
    with pytest.raises(StreamError, match="symlink"):
        StreamLedger(alias)
    alias.unlink()
    alias.hardlink_to(tmp_path / "stream.db")
    with pytest.raises(StreamError, match="Source"):
        stream_dataset(database=tmp_path / "stream.db", source=alias, dataset_format="asset")
    for cap in [0, True, "x"]:
        with pytest.raises(StreamError, match="storage"):
            StreamLedger(tmp_path / "other", max_storage_bytes=cap)
    bad = tmp_path / "bad"
    bad.write_bytes(b"not SQLite")
    with pytest.raises(StreamError, match="Cannot open"):
        StreamLedger(bad)
    other = tmp_path / "unrelated"
    with closing(sqlite3.connect(other)) as db, db:
        db.execute("CREATE TABLE private_data(secret TEXT)")
    with pytest.raises(StreamError, match="Not a streaming"):
        StreamLedger(other)


def test_saved_storage_limit_and_export_alias_guards(tmp_path, prepare):
    result = prepare()
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        contract = json.loads(ledger.job(result.job_id)["contract"])
        contract["limits"]["max_storage_bytes"] = 65_536
        with ledger.connection:
            ledger.connection.execute("UPDATE stream_jobs SET contract=?", (json.dumps(contract),))
            ledger.connection.execute("CREATE TABLE filler(x BLOB)")
            ledger.connection.execute("INSERT INTO filler VALUES(?)", (b"x" * 100_000,))
    with pytest.raises(StreamError, match="saved storage"):
        stream_dataset(database=tmp_path / "stream.db", resume=result.job_id)
    with pytest.raises(StreamError, match="storage"):
        StreamLedger(tmp_path / "stream.db", max_storage_bytes=65_536)
    with closing(StreamLedger(tmp_path / "stream.db")) as ledger:
        output = tmp_path / "alias.json"
        output.symlink_to(tmp_path / "input")
        with pytest.raises(StreamError, match="unsafe"):
            export_stream(ledger, ledger.job(result.job_id), output)


def test_cli_schema_projection_protection_and_failed_job(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.write_text('{"n":"12"}\n', encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text('{"number":{"type":"integer"}}', encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(
        '{"fields":[{"source":"/n","target":"/number","conversion":"integer"}]}', encoding="utf-8"
    )
    monkeypatch.setattr(
        "verboisy.cli.streaming.Settings",
        lambda: Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    args = [
        "stream",
        "--database",
        str(tmp_path / "stream.db"),
        "--dataset-file",
        f"jsonl={source}",
        "--schema",
        str(schema),
        "--projection",
        str(plan),
    ]
    assert CliRunner().invoke(app, args).exit_code == 0
    assert CliRunner().invoke(app, [*args, "--export", str(schema)]).exit_code == 1
    source.write_text('{"n":"wrong"}', encoding="utf-8")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1 and json.loads(result.output)["status"] == "FAILED"


def test_projected_record_cannot_escape_its_byte_ceiling(prepare):
    plan = ProjectionPlan(fields=[{"source": "/x", "target": "/" + "long" * 30}])
    result = prepare(b'{"x":"a"}\n', projection=plan, limits=StreamLimits(max_record_bytes=32))
    assert result.status == "FAILED" and "projected record byte limit" in result.reason


def test_growing_file_cannot_escape_the_input_ceiling(tmp_path):
    import verboisy.streaming.capture as capture

    source = tmp_path / "input"
    source.write_bytes(b"abc")

    class Growing(io.BytesIO):
        def fileno(self):
            return 7

    expected = source.stat()
    with (
        patch.object(Path, "open", return_value=Growing(b"abcd")),
        patch.object(capture.os, "fstat", return_value=expected),
    ):
        result = stream_dataset(
            database=tmp_path / "stream.db",
            source=source,
            dataset_format="asset",
            limits=StreamLimits(max_input_bytes=3),
            config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
        )
    assert result.status == "FAILED" and "input byte limit" in result.reason


def test_job_inventory_and_cli_status_remain_bounded(tmp_path, prepare):
    first = prepare()
    second = prepare()
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert [job["id"] for job in ledger.jobs(limit=1)] == [second.job_id]
        assert len(ledger.jobs()) == 2
        for value in [True, 0, 1001, "1"]:
            with pytest.raises(StreamError, match="inventory"):
                ledger.jobs(limit=value)
    result = CliRunner().invoke(app, ["stream-status", "--database", str(tmp_path / "stream.db")])
    assert result.exit_code == 0 and json.loads(result.output)["jobs"][1]["id"] == first.job_id
    assert (
        CliRunner()
        .invoke(app, ["stream-status", "--database", str(tmp_path / "missing")])
        .exit_code
        == 1
    )


def test_hard_process_termination_recovers_committed_rows(tmp_path):
    import os
    import subprocess
    import sys
    import time

    source = tmp_path / "input.jsonl"
    source.write_bytes(
        b'{"pad":"' + b"x" * 200 + b'"}\n' + (b'{"pad":"' + b"y" * 200 + b'"}\n') * 99999
    )
    database = tmp_path / "stream.db"
    code = (
        "from pathlib import Path; from verboisy import stream_dataset; "
        "from verboisy.utils.config import Settings; stream_dataset(database=Path("
        + repr(str(database))
        + "),source=Path("
        + repr(str(source))
        + '),dataset_format="jsonl",config=Settings(_env_file=None,dataset_local_roots=['
        + repr(str(tmp_path))
        + "]))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        str(Path(p).resolve()) for p in env.get("PYTHONPATH", "").split(os.pathsep) if p
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    checkpoint = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and child.poll() is None:
            try:
                with closing(StreamLedger(database, read_only=True)) as ledger:
                    jobs = ledger.jobs(limit=1)
                if jobs and 0 < jobs[0]["processed"] < 100000:
                    checkpoint = jobs[0]
                    break
            except StreamError:
                pass
            time.sleep(0.02)
        assert checkpoint is not None, "No intermediate committed checkpoint observed"
        child.kill()
        child.wait(timeout=10)
        source.unlink()
        # Process exit can precede completion of Windows handle cleanup. Retry
        # only lock contention, with a fixed deadline; other failures stay visible.
        deadline = time.monotonic() + 10
        while True:
            try:
                resumed = stream_dataset(database=database, resume=checkpoint["id"])
                break
            except StreamError as error:
                if (
                    str(error) != "Streaming ledger is already in use"
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.05)
        assert resumed.status == "COMPLETED" and resumed.processed_rows == 100000
        with closing(StreamLedger(database, read_only=True)) as ledger:
            assert (
                ledger.connection.execute("SELECT COUNT(*) FROM stream_rows").fetchone()[0]
                == 100000
            )
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
