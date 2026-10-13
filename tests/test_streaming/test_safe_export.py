# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Streaming publication protects inputs and keeps unescaped source evidence."""

import csv
import json
from contextlib import closing

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.streaming import StreamLedger, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.streaming.export import bundle_paths, export_stream
from verboisy.utils.config import Settings


def prepare(tmp_path, **options):
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"=header": "  =1+1", "number": -3, "blank": None}) + "\n")
    return stream_dataset(
        database=tmp_path / "stream.db",
        source=source,
        dataset_format="jsonl",
        config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
        **options,
    )


@pytest.mark.parametrize("mode", [None, "spreadsheet", "json"])
def test_formula_headers_cells_and_lossless_json_encoding(tmp_path, mode):
    output = tmp_path / "rows.csv"
    result = prepare(tmp_path, csv_mode=mode, export=output)
    with output.open(newline="") as stream:
        rows = list(csv.reader(stream))
    expected = {"=header": "  =1+1", "number": -3, "blank": None}
    if mode == "json":
        assert (
            dict(zip(map(json.loads, rows[0]), map(json.loads, rows[1]), strict=True)) == expected
        )
    else:
        assert rows == [["'=header", "number", "blank"], ["'  =1+1", "-3", ""]]
    proof = json.loads(output.with_name(output.name + ".evidence.jsonl").read_text())
    assert proof["source_values"] == expected and proof["output_is_source"] is True
    manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text())
    assert manifest["csv_mode"] == (mode or "spreadsheet")
    assert result.status == "COMPLETED"


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_every_streaming_sidecar_rejects_source_alias(tmp_path, index, alias):
    result = prepare(tmp_path)
    source = tmp_path / "input.jsonl"
    original = source.read_bytes()
    output = tmp_path / "rows.csv"
    target = bundle_paths(output)[index]
    getattr(target, "hardlink_to" if alias == "hardlink" else "symlink_to")(source)
    with (
        closing(StreamLedger(tmp_path / "stream.db")) as ledger,
        pytest.raises(StreamError, match="protected"),
    ):
        export_stream(ledger, ledger.job(result.job_id), output)
    assert source.read_bytes() == original


def test_configuration_protection_survives_resume(tmp_path):
    configuration = tmp_path / "schema.json"
    configuration.write_text("configuration")
    result = prepare(tmp_path, protected_inputs=(configuration,), rows_per_invocation=1)
    (tmp_path / "input.jsonl").unlink()
    output = tmp_path / "rows.json"
    output.hardlink_to(configuration)
    with pytest.raises(StreamError, match="protected"):
        stream_dataset(database=tmp_path / "stream.db", resume=result.job_id, export=output)
    assert configuration.read_text() == "configuration"


def test_resume_protects_newly_read_dotenv_configuration(tmp_path):
    result = prepare(tmp_path, rows_per_invocation=1)
    configuration = tmp_path / "resume-config.json"
    configuration.write_text("MAX_STEPS=3\n")
    with pytest.raises(StreamError, match="protected"):
        stream_dataset(
            database=tmp_path / "stream.db",
            resume=result.job_id,
            export=configuration,
            config=Settings(_env_file=configuration),
        )
    assert configuration.read_text() == "MAX_STEPS=3\n"


def test_invalid_modes_and_resume_contract_options(tmp_path):
    with pytest.raises(StreamError, match="CSV mode"):
        prepare(tmp_path, csv_mode="unsafe")
    result = prepare(tmp_path)
    for options in ({"csv_mode": "json"}, {"protected_inputs": ()}):
        with pytest.raises(StreamError, match="saved streaming contract"):
            stream_dataset(database=tmp_path / "stream.db", resume=result.job_id, **options)


def test_cli_csv_option_and_schema_alias(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATASET_LOCAL_ROOTS", json.dumps([str(tmp_path)]))
    source = tmp_path / "input.jsonl"
    source.write_text('{"name":"=formula"}\n')
    schema = tmp_path / "schema.json"
    schema.write_text('{"type":"object"}')
    destination = tmp_path / "rows.csv"
    args = [
        "stream",
        "--dataset-file",
        "jsonl=input.jsonl",
        "--schema",
        "schema.json",
        "--csv-mode",
        "json",
        "--export",
        str(destination),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    destination.unlink()
    destination.hardlink_to(schema)
    failed = CliRunner().invoke(app, args)
    assert failed.exit_code == 1 and schema.read_text() == '{"type":"object"}'
