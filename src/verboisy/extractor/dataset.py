# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded deterministic dataset parsing with immutable bytes and row locators."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from typing import Any, cast

from verboisy.dataset_formats import MIME_TYPES
from verboisy.dataset_formats import DatasetFormat as DatasetFormat
from verboisy.extractor.format_errors import DatasetParseError as DatasetParseError


@dataclass(frozen=True)
class SourceRow:
    row_index: int
    source_pointer: str | None
    line_start: int | None
    line_end: int | None
    values_json: str

    @property
    def values(self) -> dict[str, Any]:
        """Return an independent copy; callers cannot mutate captured source values."""
        return cast(dict[str, Any], json.loads(self.values_json))


@dataclass(frozen=True)
class ParsedDataset:
    format: DatasetFormat
    original_bytes: bytes
    sha256: str
    rows: tuple[SourceRow, ...]
    headers: tuple[str, ...]
    parser_version: str = "1"


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetParseError("Duplicate JSON object key")
        result[key] = value
    return result


def _constant(_value: str) -> Any:
    raise DatasetParseError("Non-finite JSON number")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise DatasetParseError("Non-finite JSON number")
    return result


def _json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)


def _encode_record(value: Any, max_depth: int) -> str:
    if not isinstance(value, dict):
        raise DatasetParseError("Dataset rows must be objects")
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict | list):
            if depth > max_depth:
                raise DatasetParseError("Dataset nesting limit exceeded")
            values = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in values)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded.encode("utf-8")  # Reject escaped lone Unicode surrogates, including object keys.
    return encoded


def parse_json_record(text: str, *, max_depth: int = 32) -> str:
    """Decode one object once, using the same finite/unique/depth policy as datasets.

    The caller owns byte and physical-line bounds. This function does not create
    an asset, hash a line, or decode an already validated canonical record again.
    """
    try:
        return _encode_record(_json(text), max_depth)
    except (ValueError, RecursionError, UnicodeEncodeError):
        raise DatasetParseError("Malformed dataset asset") from None


def parse_dataset(
    content: bytes,
    dataset_format: DatasetFormat,
    *,
    max_bytes: int = 16_777_216,
    max_rows: int = 100_000,
    max_depth: int = 32,
) -> ParsedDataset:
    """Parse declared UTF-8 data without coercion, evaluation or model requests.

    CSV requires unique nonempty headers and exact row widths. JSON requires an
    array of objects; JSONL requires one object per nonblank physical line.
    DOCX/XLSX use bounded OOXML adapters. Asset mode indexes immutable bytes
    without interpreting content; other textual inputs require UTF-8.
    """
    if not isinstance(content, bytes):
        raise TypeError("Dataset content must be immutable bytes")
    if max_bytes < 1 or max_rows < 0 or max_depth < 1:
        raise ValueError("Invalid dataset parser limits")
    if dataset_format not in MIME_TYPES:
        raise DatasetParseError("Unsupported dataset format")
    if len(content) > max_bytes:
        raise DatasetParseError("Dataset byte limit exceeded")
    rows: list[SourceRow] = []
    headers: tuple[str, ...] = ()

    def append(value: Any, pointer: str | None, first: int | None, last: int | None) -> None:
        if not isinstance(value, dict):
            raise DatasetParseError("Dataset rows must be objects")
        if len(rows) >= max_rows:
            raise DatasetParseError("Dataset row limit exceeded")
        encoded = _encode_record(value, max_depth)
        rows.append(SourceRow(len(rows) + 1, pointer, first, last, encoded))

    if dataset_format == "asset":
        append(
            {"sha256": hashlib.sha256(content).hexdigest(), "byte_count": len(content)},
            "/",
            None,
            None,
        )
    elif dataset_format in {"docx", "xlsx"}:
        from verboisy.extractor.docx import docx_rows
        from verboisy.extractor.xlsx import xlsx_rows

        adapter = docx_rows if dataset_format == "docx" else xlsx_rows
        for value, pointer in adapter(content, max_depth):
            append(value, pointer, None, None)
    else:
        if content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b")):
            raise DatasetParseError("Compressed assets require a separate archive policy")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DatasetParseError("Dataset is not valid UTF-8") from None
        if "\x00" in text:
            raise DatasetParseError("NUL byte in dataset text")
        if not text.strip():
            raise DatasetParseError("Empty dataset asset")
        if text.lstrip().lower().startswith(("<!doctype html", "<html", "<?xml")):
            raise DatasetParseError("Markup is not a dataset")
        if dataset_format == "text":
            for number, line in enumerate(io.StringIO(text, newline=None), 1):
                append({"text": line.removesuffix("\n")}, None, number, number)
            return ParsedDataset(
                dataset_format, content, hashlib.sha256(content).hexdigest(), tuple(rows), headers
            )
        try:
            if dataset_format in {"csv", "tsv"}:
                reader = csv.reader(
                    io.StringIO(text, newline=""),
                    strict=True,
                    delimiter="\t" if dataset_format == "tsv" else ",",
                )
                headers = tuple(next(reader))
                if not headers or any(not header.strip() for header in headers):
                    raise DatasetParseError("CSV headers must be nonempty")
                if len(set(headers)) != len(headers):
                    raise DatasetParseError("Duplicate CSV header")
                while True:
                    first = reader.line_num + 1
                    cells = next(reader, None)
                    if cells is None:
                        break
                    if len(cells) != len(headers):
                        raise DatasetParseError("CSV row width differs from header")
                    append(dict(zip(headers, cells, strict=True)), None, first, reader.line_num)
            elif dataset_format == "json":
                values = _json(text)
                if not isinstance(values, list):
                    raise DatasetParseError("JSON dataset must be an array")
                for index, value in enumerate(values):
                    append(value, f"/{index}", None, None)
            else:
                for number, line in enumerate(io.StringIO(text, newline=None), 1):
                    if line.strip():
                        append(_json(line), None, number, number)
        except (ValueError, csv.Error, RecursionError, UnicodeEncodeError, StopIteration):
            raise DatasetParseError("Malformed dataset asset") from None
    return ParsedDataset(
        dataset_format, content, hashlib.sha256(content).hexdigest(), tuple(rows), headers
    )
