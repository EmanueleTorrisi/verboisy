"""Atomic JSON and CSV exports. CSV cells are safe to open as text."""

import csv
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO


def _atomic_write(filepath: str | Path, write: Callable[[TextIO], None]) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict | list):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


class DataExporter:
    @staticmethod
    def export_json(data: list[dict[str, Any]], filepath: str | Path) -> None:
        def write(stream: TextIO) -> None:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")

        _atomic_write(filepath, write)

    @staticmethod
    def export_csv(data: list[dict[str, Any]], filepath: str | Path) -> None:
        headers = sorted({key for row in data for key in row})

        def write(stream: TextIO) -> None:
            if headers:
                writer = csv.writer(stream)
                writer.writerow([_csv_value(key) for key in headers])
                writer.writerows([_csv_value(row.get(key, "")) for key in headers] for row in data)

        _atomic_write(filepath, write)
