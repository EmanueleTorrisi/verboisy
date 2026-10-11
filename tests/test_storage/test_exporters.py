# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import csv
import json

import pytest
from verboisy.storage.exporters import DataExporter


def test_export_json_writes_nested_data(tmp_path) -> None:
    filepath = tmp_path / "nested" / "results.json"

    data = [
        {
            "name": "Alice",
            "details": {"role": "developer"},
        }
    ]

    DataExporter.export_json(data, filepath)

    assert json.loads(filepath.read_text(encoding="utf-8")) == data


def test_export_json_raises_when_file_cannot_be_written(tmp_path) -> None:
    filepath = tmp_path / "results.json"

    filepath.mkdir()

    with pytest.raises(IsADirectoryError):
        DataExporter.export_json(
            [{"name": "Alice"}],
            filepath,
        )


def test_export_csv_writes_empty_output(tmp_path) -> None:
    filepath = tmp_path / "results.csv"

    DataExporter.export_csv([], filepath)

    assert filepath.read_text() == ""


def test_export_csv_writes_headers_and_rows(tmp_path) -> None:
    filepath = tmp_path / "results.csv"

    data = [
        {
            "name": "Alice",
            "age": 30,
        },
        {
            "name": "Bob",
            "city": "Rome",
        },
    ]

    DataExporter.export_csv(data, filepath)

    with filepath.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows == [
        {"age": "30", "city": "", "name": "Alice"},
        {"age": "", "city": "Rome", "name": "Bob"},
    ]


def test_export_csv_serializes_nested_values(tmp_path) -> None:
    filepath = tmp_path / "results.csv"

    data = [
        {
            "name": "Alice",
            "tags": ["python", "testing"],
            "metadata": {"level": "senior"},
        }
    ]

    DataExporter.export_csv(data, filepath)

    with filepath.open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))

    assert json.loads(row["tags"]) == ["python", "testing"]
    assert json.loads(row["metadata"]) == {"level": "senior"}


def test_export_csv_raises_when_writing_fails(tmp_path, monkeypatch) -> None:
    filepath = tmp_path / "results.csv"
    filepath.write_text("previous output")

    def fail_replace(_self, _target):
        raise OSError("cannot replace file")

    monkeypatch.setattr("verboisy.storage.exporters.Path.replace", fail_replace)
    with pytest.raises(OSError, match="cannot replace file"):
        DataExporter.export_csv([{"name": "Alice"}], filepath)
    assert filepath.read_text() == "previous output"
    assert len(list(tmp_path.iterdir())) == 1


def test_csv_formula_cells_and_headers_are_text(tmp_path):
    filepath = tmp_path / "safe.csv"
    DataExporter.export_csv([{"=header": "  =1+1", "negative": -3}], filepath)
    with filepath.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["'=header", "negative"]
    assert rows[1] == ["'  =1+1", "-3"]
