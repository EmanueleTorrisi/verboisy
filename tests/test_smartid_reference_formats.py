# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Manifest-declared reference modes round-trip real exports without heuristic CSV decoding."""

import hashlib
import json

import pytest
from verboisy.reference_dataset import load_reference_dataset, reference_input_paths
from verboisy.streaming import stream_dataset
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


@pytest.mark.parametrize("mode", ["json", "spreadsheet"])
def test_stream_export_reference_roundtrip(tmp_path, mode):
    source = tmp_path / "source.jsonl"
    source.write_text('{"id":"A","sku":"001"}\n{"id":"B","sku":"quoted, value"}\n')
    output = tmp_path / "reference.csv"
    result = stream_dataset(
        database=tmp_path / "stream.db",
        source=source,
        dataset_format="jsonl",
        csv_mode=mode,
        export=output,
        config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    assert result.status == "COMPLETED"
    loaded = load_reference_dataset(output)
    assert loaded.rows[0] == {"id": "A", "sku": "001"} and loaded.mode == mode
    assert loaded.version == "stream-1" and loaded.manifest_sha256
    before = output.read_bytes()
    output.write_bytes(before + b"x")
    with pytest.raises(VerboisyError, match="checksum"):
        load_reference_dataset(output)


@pytest.mark.parametrize("body", ["id,sku\nA,null\nB,true\nC,001\n", 'id,sku\nA,"quoted, text"\n'])
def test_plain_csv_preserves_text(tmp_path, body):
    path = tmp_path / "reference.csv"
    path.write_text(body)
    loaded = load_reference_dataset(path)
    assert loaded.mode == "text" and loaded.manifest_path is None
    assert loaded.rows[0]["sku"] in {"null", "quoted, text"}
    assert path.with_name(path.name + ".manifest.json") in reference_input_paths(path)


@pytest.mark.parametrize(
    "body", ["id,x\nA,1,extra\n", "id,x\nA\n", "id,id\nA,B\n", "id,x\nA,1\nA,2\n", 'id,x\n"A,1\n']
)
def test_bad_csv_width_ids_syntax(tmp_path, body):
    path = tmp_path / "bad.csv"
    path.write_text(body)
    with pytest.raises(VerboisyError):
        load_reference_dataset(path)


def test_ordinary_json_csv_absence_and_null(tmp_path):
    path = tmp_path / "reference.csv"
    path.write_text('id,sku,nullable,optional\n1,"""A""",null,\n')
    manifest = {
        "format_version": 3,
        "csv_mode": "json",
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()},
    }
    path.with_name(path.name + ".manifest.json").write_text(json.dumps(manifest))
    loaded = load_reference_dataset(path)
    assert loaded.rows == [{"id": 1, "sku": "A", "nullable": None}] and loaded.mode == "json"


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {"format_version": 99},
        {"format_version": 3, "csv_mode": "guess"},
        {"format_version": 3, "csv_mode": "json", "files": {}},
    ],
)
def test_invalid_existing_manifest_never_falls_back(tmp_path, manifest):
    path = tmp_path / "rows.csv"
    path.write_text("id,x\n1,A\n")
    path.with_name(path.name + ".manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(VerboisyError):
        load_reference_dataset(path)


@pytest.mark.parametrize("limit", [True, 0, 1])
def test_reference_row_ceiling(tmp_path, limit):
    path = tmp_path / "rows.json"
    path.write_text('[{"id":1},{"id":2}]')
    with pytest.raises(VerboisyError):
        load_reference_dataset(path, max_rows=limit)
    path = tmp_path / "rows.csv"
    path.write_text("id\n1\n2\n")
    with pytest.raises(VerboisyError):
        load_reference_dataset(path, max_rows=limit)


async def test_changed_resume_reference_binding_is_rejected(tmp_path):
    from verboisy import arun

    from tests.test_storage.test_unit_replay_integrity import accept_observation, ledger

    reference = tmp_path / "reference.json"
    reference.write_text('[{"id":1,"name":"Alba","population":2}]')
    with ledger(tmp_path) as (store, rid, task):
        accept_observation(store, rid, task, "persons", name="Alba")
        store.event(rid, "product_options", {"smartid": str(reference)})
        store.finish(rid, "COMPLETED", "target_met", 0, 0)
    config = Settings(_env_file=None, sqlite_db_path=str(tmp_path / "replay.db"))
    await arun(resume=rid, config=config)
    reference.write_text('[{"id":2,"name":"Alba","population":2}]')
    with pytest.raises(VerboisyError, match="reference changed"):
        await arun(resume=rid, config=config)
