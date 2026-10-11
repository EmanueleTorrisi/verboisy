# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Profiles are bounded observations with explicit omissions and source hashes."""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.extractor.profile import DatasetProfileError, profile_dataset


def dataset(rows):
    return parse_dataset(json.dumps(rows, ensure_ascii=False).encode(), "json")


def test_mixed_types_missing_nulls_and_distinct_values():
    parsed = dataset([{"x": None}, {"x": 1, "late": True}, {"x": 1.0}, {"x": "1"}, {}, {"x": 1}])
    profile = profile_dataset(parsed)
    fields = {field.pointer: field for field in profile.fields}
    x = fields["/x"]
    assert (x.present_rows, x.missing_rows, x.null_rows) == (5, 1, 1)
    assert x.observed_types == ("integer", "null", "number", "string")
    assert x.distinct_values_sampled == 4
    assert fields["/late"].observed_types == ("boolean",)
    assert fields["/late"].missing_rows == 5
    assert profile.asset_sha256 == parsed.sha256
    assert profile.parser_version == "1"
    assert profile.profile_version == "1"
    assert not profile.rows_truncated
    assert not profile.fields_truncated
    assert profile_dataset(parsed) == profile
    with pytest.raises(FrozenInstanceError):
        profile.sampled_rows = 0
    assert parsed.rows[0].values == {"x": None}


@pytest.mark.parametrize(
    "fmt,raw",
    [
        ("csv", 'name,note\r\nAnaïs,"first\nsecond"\r\n李雷,=1+1\r\n'.encode()),
        (
            "json",
            '[{"name":"Anaïs","note":"first\\nsecond"},{"name":"李雷","note":"=1+1"}]'.encode(),
        ),
        (
            "jsonl",
            '{"name":"Anaïs","note":"first\\nsecond"}\n{"name":"李雷","note":"=1+1"}\n'.encode(),
        ),
    ],
)
def test_unicode_formulas_and_no_external_work(fmt, raw):
    parsed = parse_dataset(raw, fmt)
    forbidden = AsyncMock(side_effect=AssertionError("external work"))
    with patch("verboisy.llm.client.LLMClient.complete_json", forbidden):
        result = profile_dataset(parsed)
    forbidden.assert_not_called()
    assert result.dataset_format == fmt
    assert result.total_rows == result.sampled_rows == 2
    fields = {field.pointer: field for field in result.fields}
    assert fields["/name"].examples[0].json_preview == '"Anaïs"'
    assert fields["/note"].examples[1].json_preview == '"=1+1"'
    assert not fields["/note"].examples[1].truncated
    assert fields["/note"].examples[1].row_index == 2
    assert parsed.original_bytes == raw


def test_caps_order_missingness_and_preview_bytes():
    parsed = dataset(
        [{"first": "李雷" * 30, "second": 0}, {"first": "different", "third": 1}, {"fourth": 2}]
    )
    profile = profile_dataset(parsed, sample_rows=2, max_fields=1, max_examples=1, preview_bytes=5)
    assert profile.rows_truncated and profile.fields_truncated
    assert profile.total_rows == 3 and profile.sampled_rows == 2
    assert [f.pointer for f in profile.fields] == ["/first"]
    field = profile.fields[0]
    assert field.distinct_values_sampled == 2
    assert len(field.examples) == 1
    assert field.examples[0].truncated
    assert len(field.examples[0].json_preview.encode()) <= 5
    assert field.examples[0].json_preview == '"李'
    json.dumps(asdict(profile), ensure_ascii=False).encode("utf-8")


def test_escaped_paths_arrays_and_empty_containers():
    profile = profile_dataset(dataset([{"a/b": {"~": ["value", None]}, "empty": [], "object": {}}]))
    fields = {field.pointer: field for field in profile.fields}
    assert fields["/a~1b/~0/0"].observed_types == ("string",)
    assert fields["/a~1b/~0/1"].observed_types == ("null",)
    assert fields["/empty"].observed_types == ("array",)
    assert fields["/object"].observed_types == ("object",)


def test_no_examples_oversized_pointers_and_empty_dataset():
    result = profile_dataset(dataset([{"x" * 600: 1, "ok": 2}]), max_examples=0)
    assert result.oversized_pointers_skipped
    assert [field.pointer for field in result.fields] == ["/ok"]
    assert result.fields[0].examples == ()
    empty = profile_dataset(dataset([]))
    assert empty.fields == ()
    assert empty.sampled_rows == empty.total_rows == 0
    assert profile_dataset(dataset([{}])).fields == ()


@pytest.mark.parametrize(
    "option,value",
    [
        ("sample_rows", 0),
        ("sample_rows", 1001),
        ("sample_rows", True),
        ("sample_rows", 1.0),
        ("max_fields", 0),
        ("max_fields", 101),
        ("max_examples", -1),
        ("max_examples", 6),
        ("preview_bytes", 0),
        ("preview_bytes", 1025),
    ],
)
def test_invalid_limits(option, value):
    with pytest.raises(DatasetProfileError, match="limits"):
        profile_dataset(dataset([]), **{option: value})


@pytest.mark.parametrize("value", [float("nan"), "\ud800"])
def test_invalid_captured_values(value):
    parsed = dataset([])
    corrupt = replace(parsed, rows=(SourceRow(1, "/0", None, None, json.dumps({"bad": value})),))
    with pytest.raises(DatasetProfileError, match="Malformed"):
        profile_dataset(corrupt)


def test_digest_distinctness_does_not_conflate_json_types():
    result = profile_dataset(dataset([{"v": 1}, {"v": True}, {"v": 1.0}, {"v": "1"}]))
    assert result.fields[0].distinct_values_sampled == 4
    assert result.fields[0].observed_types == ("boolean", "integer", "number", "string")
    assert result.sample_policy == "first_rows_first_paths"


def test_container_to_scalar_changes_are_not_reported_as_missing():
    profile = profile_dataset(dataset([{"x": 1}, {"x": {"a": 2}}, {"x": [3]}, {}]))
    fields = {field.pointer: field for field in profile.fields}
    assert fields["/x"].observed_types == ("array", "integer", "object")
    assert fields["/x"].present_rows == 3
    assert fields["/x"].missing_rows == 1
    assert fields["/x/a"].present_rows == 1
    assert fields["/x/0"].present_rows == 1
