# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded SmartID input with manifest-declared formats and checksum consistency.

Manifests never select paths to read. Unmanifested CSV has text semantics; JSON
cells are decoded only under a verified exporter contract, never by heuristics.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.json_payload import decode_json, read_bytes


@dataclass(frozen=True)
class ReferenceDataset:
    rows: list[dict[str, Any]]
    path: Path
    sha256: str
    manifest_path: Path | None
    manifest_sha256: str | None
    mode: str
    version: int | str | None


def reference_input_paths(path: str | Path) -> set[Path]:
    """Protect the reference and its potential adjacent manifest, even if absent."""
    requested = Path(path).absolute()
    return {requested.resolve(), requested.with_name(requested.name + ".manifest.json").resolve()}


def load_reference_dataset(
    path: str | Path, *, max_bytes: int = 50_000_000, max_rows: int = 100_000
) -> ReferenceDataset:
    """Load unchanged regular CSV/JSON with bounded rows and unique supported IDs.

    Existing malformed manifests fail closed. Checksums establish consistency,
    not authenticity; spreadsheet escaping retains exporter text semantics.
    """
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise VerboisyError("Reference row limit must be a positive integer")
    requested = Path(path).absolute()
    source = requested.resolve()
    manifest_input = requested.with_name(requested.name + ".manifest.json")
    manifest_path = manifest_input.resolve()
    manifest_hash = None
    version: int | str | None = None
    mode: str = "text"
    try:
        data = read_bytes(source, max_bytes=max_bytes)
        digest = hashlib.sha256(data).hexdigest()
        if manifest_path.exists() or manifest_input.is_symlink():
            raw_manifest = read_bytes(manifest_path, max_bytes=1_048_576)
            manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
            manifest = decode_json(raw_manifest)
            if not isinstance(manifest, dict):
                raise ValueError("Invalid reference manifest")
            version = manifest.get("format_version", manifest.get("manifest_version"))
            if (
                not isinstance(version, int) or isinstance(version, bool) or version != 3
            ) and version != "stream-1":
                raise ValueError("Unsupported reference manifest version")
            mode = manifest.get("csv_mode", "")
            if mode not in ("json", "spreadsheet"):
                raise ValueError("Invalid reference CSV mode")
            if (
                not isinstance(manifest.get("files"), dict)
                or manifest["files"].get(requested.name) != digest
            ):
                raise ValueError("Reference checksum mismatch")
        if source.suffix.lower() == ".json":
            rows = decode_json(data)
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError("JSON reference must be an array of objects")
        elif source.suffix.lower() == ".csv":
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
            header = next(reader, [])
            if mode == "json" and version == "stream-1":
                header = [decode_json(cell) for cell in header]
            if (
                not header
                or any(not isinstance(name, str) or not name.strip() for name in header)
                or len(set(header)) != len(header)
            ):
                raise ValueError(
                    "CSV dataset must have a nonempty header row with no duplicate column names"
                )
            rows = []
            for cells in reader:
                if len(cells) != len(header):
                    raise ValueError("CSV row width differs from header")
                rows.append(
                    {
                        key: decode_json(cell) if mode == "json" else cell
                        for key, cell in zip(header, cells, strict=True)
                        if mode != "json" or cell != ""
                    }
                )
                if len(rows) > max_rows:
                    raise ValueError("Reference exceeds row limit")
        else:
            raise ValueError("Reference must be CSV or JSON")
        if len(rows) > max_rows:
            raise ValueError("Reference exceeds row limit")
        ids = set()
        for row in rows:
            value = row.get("id")
            if isinstance(value, str) and value.strip():
                value = value.strip()
                value = int(value) if value.isdecimal() else value
            if isinstance(value, int) and not isinstance(value, bool) and value < 1:
                raise ValueError("Dataset has an invalid row id")
            if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
                raise ValueError("Dataset is missing a row id")
            if value in ids:
                raise ValueError("Reference contains duplicate ids")
            ids.add(value)
            row["id"] = value
    except (OSError, ValueError, TypeError, csv.Error) as error:
        raise VerboisyError(
            "Cannot verify reference dataset: " + str(error)
            if isinstance(error, ValueError)
            else "Cannot read dataset as a regular reference file"
        ) from None
    return ReferenceDataset(
        rows, source, digest, manifest_path if manifest_hash else None, manifest_hash, mode, version
    )
