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


def test_export_csv_returns_without_writing_for_empty_data(tmp_path) -> None:
    filepath = tmp_path / "results.csv"

    DataExporter.export_csv([], filepath)

    assert not filepath.exists()


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

    class BrokenFile:
        def __enter__(self):
            raise OSError("cannot open file")

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(
        "verboisy.storage.exporters.Path.open",
        lambda _self, *_args, **_kwargs: BrokenFile(),
    )

    with pytest.raises(OSError, match="cannot open file"):
        DataExporter.export_csv(
            [{"name": "Alice"}],
            filepath,
        )
