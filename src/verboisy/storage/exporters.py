# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Atomic JSON and CSV exports. CSV cells are safe to open as text."""

import csv
import errno
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO


def sync_directory(path: Path) -> bool:
    """Sync POSIX directory entries; return False only for unsupported operations.

    Windows and filesystems rejecting directory fsync provide atomic replacement
    but no asserted power-loss durability. Real storage errors propagate.
    """
    if os.name != "posix":
        return False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        if error.errno in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return False
        raise
    return True


def _atomic_write(filepath: str | Path, write: Callable[[TextIO], None]) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure consistent behavior across Windows, Linux, and macOS.
    if path.is_dir():
        raise IsADirectoryError(
            errno.EISDIR,
            os.strerror(errno.EISDIR),
            str(path),
        )

    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())

        # The temporary file lives beside its destination so replacement stays on
        # one filesystem; readers see a complete old or new file, never partial output.
        Path(temporary).replace(path)
        sync_directory(path.parent)

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
