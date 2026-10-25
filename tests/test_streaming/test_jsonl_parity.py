# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Strict JSONL replay retains exact typed values, bounds and source locations."""

import io
import json
import random

import pytest
from verboisy.extractor.dataset import parse_dataset, parse_json_record
from verboisy.streaming.contract import StreamError
from verboisy.streaming.parser import source_rows
from verboisy.utils.exceptions import VerboisyError


def test_streaming_and_bounded_decoders_preserve_types_and_locations():
    rng = random.Random(713)
    atoms = [
        None,
        False,
        True,
        1,
        1.0,
        -0.0,
        10**30,
        "東京",
        "a\nb",
        [1, False, None],
        {"x/y": ["~"]},
    ]
    expected = [{"n": i, "value": rng.choice(atoms)} for i in range(200)]
    raw = (
        "\ufeff\r\n"
        + "\r\n\r\n".join(json.dumps(row, ensure_ascii=False) for row in expected)
        + "\r\n"
    ).encode()
    bounded = parse_dataset(raw, "jsonl")
    streamed = list(source_rows(io.BytesIO(raw), "jsonl", 8192))
    assert streamed == list(bounded.rows)
    assert [row.values_json for row in streamed] == [
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in expected
    ]


@pytest.mark.parametrize(
    "line",
    [
        '{"a":1,"a":2}',
        '{"a":1,"\\u0061":2}',
        '{"x":{"a":1,"a":2}}',
        '{"n":NaN}',
        '{"n":Infinity}',
        '{"n":-Infinity}',
        '{"n":1e10000}',
        '{"x":"\\ud800"}',
        '{"\\udfff":1}',
        '{"a":1} trailing',
        "[]",
        "null",
        "1",
        '{"a":1,}',
        '{"x":' + "[" * 1000 + "0" + "]" * 1000 + "}",
        '{"x":' + "[" * 32 + "0" + "]" * 32 + "}",
    ],
)
def test_invalid_or_ambiguous_records_are_rejected_by_both_paths(line):
    with pytest.raises(VerboisyError):
        parse_dataset(line.encode(), "jsonl")
    with pytest.raises(VerboisyError):
        list(source_rows(io.BytesIO(line.encode()), "jsonl", 16384))


def test_depth_boundary_and_bom_are_asset_level_not_per_record():
    line = '{"x":' + "[" * 31 + "0" + "]" * 31 + "}"
    assert parse_json_record(line) == line
    raw = b'{"a":1}\n' + '\ufeff{"a":2}\n'.encode()
    with pytest.raises(VerboisyError):
        parse_dataset(raw, "jsonl")
    rows = source_rows(io.BytesIO(raw), "jsonl", 1024)
    assert next(rows).values == {"a": 1}
    with pytest.raises(VerboisyError):
        next(rows)


@pytest.mark.parametrize("raw,ceiling", [(b'{"a":"xxxx"}\n', 8), ('{"x":"東京"}\n'.encode(), 12)])
def test_jsonl_physical_byte_limits_still_apply(raw, ceiling):
    with pytest.raises(StreamError, match="byte limit"):
        list(source_rows(io.BytesIO(raw), "jsonl", ceiling))


def test_decoded_limit_counts_expanding_escape_characters():
    # Compact exponent expands to a longer canonical float representation.
    raw = b'{"x":1e20}'
    with pytest.raises(StreamError, match="decoded record byte limit"):
        list(source_rows(io.BytesIO(raw), "jsonl", len(raw)))
