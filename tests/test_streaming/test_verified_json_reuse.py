# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Canonical reuse retains typed values, schema checks and source-bound proofs."""

import hashlib
import json
import random
import sqlite3
from contextlib import closing

import pytest
from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.streaming import StreamLedger, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.streaming.export import _proof_line, bundle_paths, export_stream
from verboisy.utils.config import Settings


@pytest.fixture
def prepare(tmp_path):
    def invoke(records, **kwargs):
        source = tmp_path / "input.jsonl"
        source.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
            encoding="utf-8",
        )
        return stream_dataset(
            database=tmp_path / "stream.db",
            source=source,
            dataset_format="jsonl",
            config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
            **kwargs,
        )

    return invoke


def test_verified_proof_bytes_match_independent_object_serialization():
    rng = random.Random(61106)
    atoms = [
        None,
        False,
        True,
        1,
        1.0,
        -0.0,
        10**60,
        1e-300,
        "東京 Pécsi",
        'quote" slash\\ newline\n\t\u0000',
        '\\ud800 },"injected":true,{',
        "\U0001f680\u2028\u2029",
        [1, False, {"nested": [None, "東京"]}],
    ]
    values = [{"sequence": index, "x": rng.choice(atoms)} for index in range(150)]
    raw = "\n".join(json.dumps(row, ensure_ascii=False) for row in values).encode()
    for source, expected in zip(parse_dataset(raw, "jsonl").rows, values, strict=True):
        for output in (expected, {"renamed": expected["x"]}):
            encoded = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
            observed = _proof_line(source, encoded, "job-東京", source.row_index)
            proof = {
                "output_row": source.row_index,
                "source_row": source.row_index,
                "record_id": hashlib.sha256(
                    f"verboisy:stream:job-東京:{source.row_index}".encode()
                ).hexdigest(),
                "line_start": source.line_start,
                "line_end": source.line_end,
                "source_values": expected,
                "output_is_source": output is expected,
            }
            if output is not expected:
                proof["output_values"] = output
            assert observed == json.dumps(proof, ensure_ascii=False, separators=(",", ":")) + "\n"


def test_resume_still_rejects_boolean_for_integer_schema(prepare, tmp_path):
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    first = prepare([{"n": 1}, {"n": 2}, {"n": True}], schema=schema, rows_per_invocation=1)
    assert first.status == "PAUSED" and first.processed_rows == 1
    (tmp_path / "input.jsonl").unlink()
    resumed = stream_dataset(
        database=tmp_path / "stream.db", resume=first.job_id, config=Settings(_env_file=None)
    )
    assert resumed.status == "FAILED" and resumed.processed_rows == 1
    assert "schema rejected" in resumed.reason


@pytest.mark.parametrize("suffix", ["jsonl", "json", "csv"])
def test_projected_proof_preserves_source_types_and_converted_output(prepare, tmp_path, suffix):
    source = {"n": "12", "note": '東京\n"}\\'}
    projection = ProjectionPlan(
        fields=[{"source": "/n", "target": "/value", "conversion": "integer"}]
    )
    output = tmp_path / ("rows." + suffix)
    result = prepare(
        [source], projection=projection, schema={"value": {"type": "integer"}}, export=output
    )
    assert result.status == "COMPLETED"
    proof = json.loads(bundle_paths(output)[1].read_text(encoding="utf-8"))
    assert proof["source_values"] == source
    assert proof["output_values"] == {"value": 12}
    assert proof["output_is_source"] is False
    value = proof["output_values"]["value"]
    assert isinstance(value, int) and not isinstance(value, bool)
    manifest = json.loads(bundle_paths(output)[3].read_text(encoding="utf-8"))
    for name, wanted in manifest["files"].items():
        assert hashlib.sha256((output.parent / name).read_bytes()).hexdigest() == wanted


@pytest.mark.parametrize(
    "column,value",
    [
        ("source_json", '{"n":1,"n":1}'),
        ("source_json", '{"n":1,"hidden":"\\ud800"}'),
        ("source_json", '{"n":NaN}'),
        ("output_json", '{"n":true}'),
        ("output_json", '{"n":1,"n":1}'),
        ("output_json", '{"n":1},"injected":true'),
    ],
)
def test_untrusted_saved_json_cannot_replace_existing_bundle(prepare, tmp_path, column, value):
    result = prepare([{"n": 1}])
    target = tmp_path / "prior.jsonl"
    paths = bundle_paths(target)
    for path in paths:
        path.write_bytes(b"previous generation")
    with sqlite3.connect(tmp_path / "stream.db") as db:
        db.execute(f"UPDATE stream_rows SET {column}=?", (value,))
    with (
        closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger,
        pytest.raises(StreamError),
    ):
        export_stream(ledger, ledger.job(result.job_id), target)
    assert all(path.read_bytes() == b"previous generation" for path in paths)


def test_export_rechecks_schema_before_reusing_verified_fragments(prepare, tmp_path):
    result = prepare([{"n": 1}])
    with sqlite3.connect(tmp_path / "stream.db") as db:
        contract = json.loads(db.execute("SELECT contract FROM stream_jobs").fetchone()[0])
        contract["schema"] = {"type": "object", "properties": {"n": {"type": "string"}}}
        db.execute("UPDATE stream_jobs SET contract=?", (json.dumps(contract),))
    output = tmp_path / "invalid.jsonl"
    with (
        closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger,
        pytest.raises(StreamError),
    ):
        export_stream(ledger, ledger.job(result.job_id), output)
    assert not any(path.exists() for path in bundle_paths(output))


def test_json_export_uses_one_source_decode_per_row_for_schema(prepare, tmp_path, monkeypatch):
    expected = [{"n": i, "nested": [True, None, {"x": "東京"}]} for i in range(4)]
    result = prepare(expected)
    decode = SourceRow.values.fget
    calls = []

    def tracked(row):
        calls.append(row.row_index)
        return decode(row)

    monkeypatch.setattr(SourceRow, "values", property(tracked))
    output = tmp_path / "verified.jsonl"
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        export_stream(ledger, ledger.job(result.job_id), output)
    assert calls == [1, 2, 3, 4]
    assert [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ] == expected
    proofs = [
        json.loads(line)
        for line in bundle_paths(output)[1].read_text(encoding="utf-8").splitlines()
    ]
    assert [proof["source_values"] for proof in proofs] == expected
