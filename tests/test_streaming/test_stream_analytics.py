# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise bundle boundaries against the real replay and capture ledger."""

import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import verboisy.streaming.analytics as engine
from verboisy.streaming import (
    AnalyticalExport,
    analytics_io,
    export_stream_analytics,
    stream_dataset,
)
from verboisy.streaming.contract import StreamError
from verboisy.utils.config import Settings

ROWS = [
    {"id": 1, "name": "Élan", "details": {"values": [None, True]}},
    {"id": 2, "name": "三", "details": {"values": [2, 1.5]}},
    {"id": 3, "name": "004", "details": {"values": []}},
]


def prepare(folder, rows, dataset_format="jsonl", *, raw=None):
    source = folder / "capture.input"
    if raw is None:
        raw = b"".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            for row in rows
        )
    source.write_bytes(raw)
    database = folder / "capture.db"
    settings_file = folder / "saved-settings.json"
    settings_file.write_bytes(b"{}")
    job = stream_dataset(
        database=database,
        source=source,
        dataset_format=dataset_format,
        config=Settings(_env_file=None, dataset_local_roots=[str(folder)]),
        protected_inputs=(settings_file,),
    )
    assert job.status == "COMPLETED", job.reason
    return database, job.job_id, source, raw


@pytest.fixture
def ready(tmp_path):
    return prepare(tmp_path, ROWS)


def export(ready, output, **kwargs):
    database, job_id, _, _ = ready
    return export_stream_analytics(database=database, job_id=job_id, output_dir=output, **kwargs)


def load_manifest(result):
    return json.loads(result.manifest.read_bytes())


def test_shards_bind_exact_values_and_coordinates_even_after_input_removal(ready, tmp_path):
    database, job_id, source, raw = ready
    before = database.read_bytes()
    source.unlink()
    output = tmp_path / "analytics"
    result = export(ready, output, shard_rows=2)
    manifest = load_manifest(result)
    assert isinstance(result, AnalyticalExport)
    assert manifest["version"] == "stream-analytics-1"
    assert manifest["rows"] == result.rows == 3 and result.shards == 2
    assert manifest["format"] == "jsonl.gz" and manifest["column_contract"] is None
    assert manifest["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["source"]["capture_included"] is False
    assert manifest["job_id"] == job_id
    assert str(source) not in result.manifest.read_text(encoding="utf-8")
    assert manifest["truth_verified"] is False and manifest["global_completeness_claimed"] is False
    assert [s["rows"] for s in manifest["shards"]] == [2, 1]
    assert [s["first_output_row"] for s in manifest["shards"]] == [1, 3]
    assert result.output_bytes == sum(path.stat().st_size for path in output.iterdir())
    values = []
    for shard in manifest["shards"]:
        files = []
        for key in ("data", "evidence"):
            info = shard[key]
            encoded = (output / info["name"]).read_bytes()
            assert len(encoded) == info["bytes"]
            assert hashlib.sha256(encoded).hexdigest() == info["sha256"]
            files.append(gzip.decompress(encoded).splitlines())
        for line, proof in zip(*files, strict=True):
            values.append(json.loads(line))
            info = json.loads(proof)
            i = len(values)
            assert info["output_row"] == info["source_row"] == info["line_start"] == i
            assert info["line_end"] == i
            assert info["output_sha256"] == hashlib.sha256(line).hexdigest()
            key = f"verboisy:stream:{job_id}:{i}".encode()
            assert info["record_id"] == hashlib.sha256(key).hexdigest()
    assert values == ROWS
    assert database.read_bytes() == before


def test_shards_split_on_payload_bytes_and_enforce_a_shard_count(ready, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "SHARD_PAYLOAD_BYTES", 80)
    result = export(ready, tmp_path / "by-bytes", shard_rows=10)
    assert [s["rows"] for s in load_manifest(result)["shards"]] == [1, 1, 1]
    monkeypatch.setattr(engine, "MAX_SHARDS", 2)
    output = tmp_path / "too-many"
    with pytest.raises(StreamError, match="shard count"):
        export(ready, output, shard_rows=10)
    assert not output.exists()


def test_budget_applies_through_final_manifest_and_preserves_input(ready, tmp_path):
    result = export(ready, tmp_path / "measure")
    output = tmp_path / "limited"
    before = ready[0].read_bytes()
    with pytest.raises(StreamError, match="output byte limit"):
        export(ready, output, max_output_bytes=result.output_bytes - 1)
    assert not output.exists() and ready[0].read_bytes() == before


def test_corrupt_late_row_cannot_publish_earlier_shards(ready, tmp_path):
    database, job_id, _, _ = ready
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE stream_rows SET output_json=? WHERE job_id=? AND ordinal=3",
            ('{"id":999}', job_id),
        )
    output = tmp_path / "corrupt"
    with pytest.raises(StreamError, match="evidence differs"):
        export(ready, output, shard_rows=1)
    assert not output.exists()


def test_existing_targets_and_removed_input_paths_are_protected(ready, tmp_path):
    database, _, source, _ = ready
    existing = tmp_path / "existing"
    existing.mkdir()
    preserved = existing / "untouched"
    preserved.write_bytes(b"original")
    source.unlink()
    original = database.read_bytes()
    settings_file = tmp_path / "saved-settings.json"
    settings_file.unlink()
    for path in (database, source, existing, settings_file):
        with pytest.raises(StreamError, match="new directory"):
            export(ready, path)
    assert not source.exists() and not settings_file.exists() and database.read_bytes() == original
    assert preserved.read_bytes() == b"original"


def test_export_refuses_incomplete_jobs_and_opaque_assets(ready, tmp_path):
    database, job_id, _, _ = ready
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE stream_jobs SET status='PAUSED' WHERE id=?", (job_id,))
    output = tmp_path / "paused"
    with pytest.raises(StreamError, match="completed streaming job"):
        export(ready, output)
    assert not output.exists()
    assets = tmp_path / "assets"
    assets.mkdir()
    with pytest.raises(StreamError, match="Opaque assets"):
        export(prepare(assets, ROWS, "asset"), tmp_path / "opaque")


def test_empty_completed_stream_has_one_valid_empty_shard(tmp_path):
    result = export(prepare(tmp_path, [], "csv", raw=b"id,name\n"), tmp_path / "empty")
    shard = load_manifest(result)["shards"][0]
    assert result.rows == shard["rows"] == 0 and result.shards == 1
    for name in ("data", "evidence"):
        assert gzip.decompress((result.manifest.parent / shard[name]["name"]).read_bytes()) == b""


def test_unavailable_read_snapshot_fails_before_creating_files(ready, tmp_path, monkeypatch):
    ledger = SimpleNamespace(
        connection=SimpleNamespace(execute=Mock(side_effect=sqlite3.OperationalError("busy"))),
        close=Mock(),
    )
    open_ledger = Mock(return_value=ledger)
    monkeypatch.setattr(engine, "StreamLedger", open_ledger)
    output = tmp_path / "busy"
    with pytest.raises(StreamError, match="consistent streaming ledger snapshot"):
        export(ready, output)
    assert not output.exists()
    open_ledger.assert_called_once_with(ready[0], read_only=True)
    ledger.close.assert_called_once()


PARQUET_COLUMNS = {
    "version": "1",
    "columns": [
        {"name": "name", "type": "string", "nullable": False},
        {"name": "id", "type": "int64", "nullable": False},
        {"name": "details", "type": "json", "nullable": True},
    ],
}


@pytest.fixture
def arrow_backend(monkeypatch):
    """Record the encoder interface without requiring Arrow in the core CI environment."""
    batches = []

    class Writer:
        def __init__(self, sink, schema, **options):
            self.sink = sink
            assert [field.name for field in schema] == ["name", "id", "details"]
            assert schema[0].nullable is False and schema[2].nullable is True
            assert options["compression"] == "zstd" and options["use_dictionary"] is False

        def __enter__(self):
            return self

        def write_batch(self, batch):
            batches.append(batch)
            self.sink.write(b"test batch")

        def __exit__(self, _kind, _error, _traceback):
            return False

    arrow = SimpleNamespace(
        Codec=SimpleNamespace(is_available=lambda name: name == "zstd"),
        bool_=lambda: "bool",
        int64=lambda: "int64",
        float64=lambda: "float64",
        string=lambda: "string",
        field=lambda name, kind, nullable: SimpleNamespace(name=name, type=kind, nullable=nullable),
        schema=tuple,
        array=lambda values, **_options: tuple(values),
        RecordBatch=SimpleNamespace(from_arrays=lambda arrays, **_options: arrays),
    )
    modules = {"pyarrow": arrow, "pyarrow.parquet": SimpleNamespace(ParquetWriter=Writer)}
    monkeypatch.setattr(analytics_io, "import_module", modules.__getitem__)
    return batches


@pytest.mark.parametrize(("rows", "size", "groups"), [(2, 16_384, [2, 1]), (10, 80, [1, 1, 1])])
def test_parquet_encoder_bounds_batches_and_preserves_physical_types(
    ready, tmp_path, monkeypatch, arrow_backend, rows, size, groups
):
    monkeypatch.setattr(analytics_io, "GROUP_ROWS", rows)
    monkeypatch.setattr(analytics_io, "GROUP_BYTES", size)
    result = export(
        ready, tmp_path / "parquet", output_format="parquet", column_contract=PARQUET_COLUMNS
    )
    manifest = load_manifest(result)
    assert manifest["format"] == "parquet" and manifest["compression"] == "zstd"
    assert manifest["column_contract"] == PARQUET_COLUMNS
    assert [len(batch[0]) for batch in arrow_backend] == groups
    actual = [row for batch in arrow_backend for row in zip(*batch, strict=True)]
    assert actual == [
        (v["name"], v["id"], json.dumps(v["details"], separators=(",", ":"))) for v in ROWS
    ]


def test_parquet_refuses_extra_columns_and_incompatible_values(tmp_path, arrow_backend):
    for label, last, error in (
        ("shape", {**ROWS[-1], "extra": 1}, "exactly the declared columns"),
        ("type", {**ROWS[-1], "id": True}, "Parquet column 'id'"),
    ):
        folder = tmp_path / label
        folder.mkdir()
        dataset = prepare(folder, [*ROWS[:-1], last])
        output = folder / "bundle"
        with pytest.raises(StreamError, match=error):
            export(
                dataset,
                output,
                output_format="parquet",
                column_contract=PARQUET_COLUMNS,
                shard_rows=1,
            )
        assert not output.exists()


def test_empty_parquet_publishes_declared_schema_without_fabricating_rows(tmp_path, arrow_backend):
    ready = prepare(tmp_path, [], "csv", raw=b"name,id,details\n")
    result = export(
        ready, tmp_path / "empty-parquet", output_format="parquet", column_contract=PARQUET_COLUMNS
    )
    assert result.rows == 0 and result.shards == 1 and not arrow_backend
    manifest = load_manifest(result)
    assert manifest["column_contract"] == PARQUET_COLUMNS
    assert manifest["shards"][0]["rows"] == 0


def test_missing_parquet_backend_does_not_create_a_bundle(ready, tmp_path, monkeypatch):
    monkeypatch.setattr(
        analytics_io, "import_module", Mock(side_effect=ModuleNotFoundError("pyarrow"))
    )
    output = tmp_path / "no-arrow"
    with pytest.raises(StreamError, match="needs a working PyArrow"):
        export(ready, output, output_format="parquet", column_contract=PARQUET_COLUMNS)
    assert not output.exists()


def test_parquet_requires_a_working_compression_codec(ready, tmp_path, monkeypatch):
    arrow = SimpleNamespace(Codec=SimpleNamespace(is_available=lambda _name: False))
    monkeypatch.setattr(analytics_io, "import_module", lambda _name: arrow)
    output = tmp_path / "no-zstd"
    with pytest.raises(StreamError, match="does not support Zstandard"):
        export(ready, output, output_format="parquet", column_contract=PARQUET_COLUMNS)
    assert not output.exists()
