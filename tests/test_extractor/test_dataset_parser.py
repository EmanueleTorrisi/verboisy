# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal dataset parsing preserves input bytes and rejects destructive ambiguity."""

import csv
import hashlib
import io
import json
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.extractor.dataset import DatasetParseError, parse_dataset

ROWS = [
    {"person": "Anaïs", "years": 31, "note": 'Contains comma, and "quotes"'},
    {"person": "李雷", "years": 22, "note": "Two\nlines"},
    {"person": "Missing age", "years": None, "note": "=1+1"},
]


def csv_bytes():
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(ROWS[0]))
    writer.writeheader()
    writer.writerows(ROWS)
    return stream.getvalue().encode()


@pytest.mark.parametrize("kind", ["csv", "json", "jsonl"])
def test_fixture_rows_and_immutable_bytes(kind):
    contents = {
        "csv": csv_bytes(),
        "json": json.dumps(ROWS, ensure_ascii=False).encode(),
        "jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ROWS).encode(),
    }
    raw = contents[kind]
    forbidden = AsyncMock(side_effect=AssertionError("Unexpected model"))
    with patch("verboisy.llm.client.LLMClient.complete_json", forbidden):
        parsed = parse_dataset(raw, kind)
    forbidden.assert_not_called()
    expected = (
        ROWS
        if kind != "csv"
        else [
            {key: "" if value is None else str(value) for key, value in row.items()} for row in ROWS
        ]
    )
    assert [row.values for row in parsed.rows] == expected
    assert parsed.original_bytes == raw
    assert parsed.sha256 == hashlib.sha256(raw).hexdigest()
    assert parsed.parser_version == "1"
    assert [row.row_index for row in parsed.rows] == [1, 2, 3]
    altered = parsed.rows[0].values
    altered["person"] = "Mutated"
    assert parsed.rows[0].values["person"] == "Anaïs"
    with pytest.raises(FrozenInstanceError):
        parsed.sha256 = "bad"
    if kind == "csv":
        assert parsed.headers == ("person", "years", "note")
        assert [(row.line_start, row.line_end) for row in parsed.rows] == [(2, 2), (3, 4), (5, 5)]
        assert all(row.source_pointer is None for row in parsed.rows)
    elif kind == "json":
        assert [row.source_pointer for row in parsed.rows] == ["/0", "/1", "/2"]
        assert all(row.line_start is None and row.line_end is None for row in parsed.rows)
    else:
        assert [row.line_start for row in parsed.rows] == [1, 2, 3]


@pytest.mark.parametrize(
    "kind,content",
    [
        ("csv", b"person,person\nAlice,Bob\n"),
        ("csv", b"person,years\nAlice,31,unexpected\n"),
        ("csv", b"person,years\nAlice\n"),
        ("json", b'[{"person":"Alice","person":"Bob"}]'),
        ("json", b'[{"person":"Alice","years":NaN}]'),
        ("jsonl", b'{"person":"Alice"}\n42\n'),
        ("csv", b"<!doctype html><html><body>Access denied</body></html>"),
        ("csv", b"person,years\n\xff,31\n"),
    ],
)
def test_eight_rejection_fixtures(kind, content):
    with pytest.raises(DatasetParseError):
        parse_dataset(content, kind)


@pytest.mark.parametrize(
    "kind,content",
    [
        ("csv", b""),
        ("csv", b" \n"),
        ("json", b"{}"),
        ("json", b"[null]"),
        ("json", b"[1]"),
        ("json", b"[[]]"),
        ("json", b'[{"n":Infinity}]'),
        ("json", b'[{"n":-Infinity}]'),
        ("json", b'[{"n":1e999}]'),
        ("json", b'[{"x":"\\ud800"}]'),
        ("json", b"[{"),
        ("jsonl", b"{}\n{"),
        ("csv", b"name, \nAlice,x\n"),
        ("csv", b"name\n\n"),
        ("csv", b'name\n"unclosed'),
        ("csv", b"name\nA\x00\n"),
        ("csv", b"<HTML>bad</HTML>"),
        ("csv", b"<?xml version='1.0'?>"),
        ("csv", b"PK\x03\x04data"),
        ("csv", b"PK\x05\x06data"),
        ("csv", b"\x1f\x8bdata"),
    ],
)
def test_malformed_and_unsupported_assets(kind, content):
    with pytest.raises(DatasetParseError):
        parse_dataset(content, kind)


@pytest.mark.parametrize(
    "kind,content", [("json", b'[{"n":1.25}]'), ("jsonl", b'\n{"n":1.25}\n\n{"n":null}\n')]
)
def test_finite_numbers_and_physical_blank_line_positions(kind, content):
    parsed = parse_dataset(content, kind)
    assert parsed.rows[0].values == {"n": 1.25}
    if kind == "jsonl":
        assert [row.line_start for row in parsed.rows] == [2, 4]


@pytest.mark.parametrize("kind,content", [("csv", b"name\n"), ("json", b"[]")])
def test_empty_collection_is_not_empty_asset(kind, content):
    assert parse_dataset(content, kind).rows == ()


def test_byte_row_depth_limits_and_exact_boundaries():
    raw = b'[{"a":{"b":1}}]'
    assert parse_dataset(raw, "json", max_bytes=len(raw), max_rows=1, max_depth=2).rows
    for limits in [{"max_bytes": len(raw) - 1}, {"max_rows": 0}, {"max_depth": 1}]:
        with pytest.raises(DatasetParseError):
            parse_dataset(raw, "json", **limits)
    assert parse_dataset(b'[{"a":[1]}]', "json", max_depth=2).rows
    with pytest.raises(DatasetParseError):
        parse_dataset(b'[{"a":[[]]}]', "json", max_depth=2)


@pytest.mark.parametrize("limits", [{"max_bytes": 0}, {"max_rows": -1}, {"max_depth": 0}])
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        parse_dataset(b"[]", "json", **limits)


def test_unsupported_format_and_mutable_content():
    with pytest.raises(DatasetParseError):
        parse_dataset(b"name\nAlice", "xlsx")
    with pytest.raises(TypeError):
        parse_dataset(bytearray(b"[]"), "json")


@pytest.mark.parametrize(
    "kind,content",
    [
        ("csv", b"name\r\nAnais\r\n"),
        ("json", b'[{"name":"Anais"}]'),
        ("jsonl", b'{"name":"Anais"}\r\n'),
    ],
)
def test_utf8_bom_preserves_original_bytes(kind, content):
    raw = b"\xef\xbb\xbf" + content
    parsed = parse_dataset(raw, kind)
    assert parsed.original_bytes == raw
    assert parsed.rows[0].values == {"name": "Anais"}


def test_deep_json_is_rejected_without_raw_recursion_error():
    content = b'[{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}]"
    with pytest.raises(DatasetParseError):
        parse_dataset(content, "json")
