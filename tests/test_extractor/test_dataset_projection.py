# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit projection preserves source locators and rejects ambiguous conversions."""

import json
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.extractor.projection import ProjectionError, ProjectionPlan, project_row


def plan(fields):
    return ProjectionPlan.model_validate({"fields": fields})


def project(value, mode="identity"):
    row = parse_dataset(json.dumps([{"raw": value}]).encode(), "json").rows[0]
    return project_row(row, plan([{"source": "/raw", "target": "/value", "conversion": mode}]))


@pytest.mark.parametrize(
    "fmt,raw",
    [
        ("csv", 'Source,Age\r\n"Anaïs\n李雷",31\r\n'.encode()),
        ("json", '[{"Source":"Anaïs\\n李雷","Age":"31"}]'.encode()),
        ("jsonl", '\n{"Source":"Anaïs\\n李雷","Age":"31"}\n'.encode()),
    ],
)
def test_rename_conversion_lineage(fmt, raw):
    dataset = parse_dataset(raw, fmt)
    row = dataset.rows[0]
    result = project_row(
        row,
        plan(
            [
                {"source": "/Source", "target": "/person/name"},
                {"source": "/Age", "target": "/person/years", "conversion": "integer"},
            ]
        ),
    )
    assert result.values == {"person": {"name": "Anaïs\n李雷", "years": 31}}
    assert result.projection_version == "1"
    assert (result.row_index, result.source_pointer, result.line_start, result.line_end) == (
        row.row_index,
        row.source_pointer,
        row.line_start,
        row.line_end,
    )
    assert result.derivations[1].source_pointer == "/Age"
    assert result.derivations[1].output_pointer == "/person/years"
    assert result.derivations[1].source_value_json == '"31"'
    assert result.derivations[1].output_value_json == "31"
    assert result.derivations[1].conversion == "integer"
    assert dataset.original_bytes == raw
    assert row.values["Age"] == "31"
    changed = result.values
    changed["person"]["years"] = 0
    assert result.values["person"]["years"] == 31
    with pytest.raises(FrozenInstanceError):
        result.row_index = 0


@pytest.mark.parametrize(
    "value,mode,expected",
    [
        ({"a": [1, None]}, "identity", {"a": [1, None]}),
        ("=1+1", "identity", "=1+1"),
        ("9007199254740993", "integer", 9007199254740993),
        (-42, "integer", -42),
        ("-0", "integer", 0),
        ("0.1", "number", 0.1),
        ("1e-9", "number", 1e-9),
        (123, "number", 123),
        (1.5, "number", 1.5),
        ("true", "boolean", True),
        ("false", "boolean", False),
        (True, "boolean", True),
        (False, "string", "false"),
        (123, "string", "123"),
        (1.5, "string", "1.5"),
        ("李雷", "string", "李雷"),
    ],
)
def test_explicit_conversions(value, mode, expected):
    output = project(value, mode).values["value"]
    assert output == expected
    assert type(output) is type(expected)


@pytest.mark.parametrize("mode", ["identity", "integer", "number", "boolean", "string"])
def test_null_is_preserved(mode):
    assert project(None, mode).values == {"value": None}


@pytest.mark.parametrize(
    "value,mode",
    [
        (" 31", "integer"),
        ("01", "integer"),
        ("1.0", "integer"),
        (1.0, "integer"),
        (True, "integer"),
        (False, "number"),
        ("1,000", "number"),
        ("NaN", "number"),
        ("1e999", "number"),
        ("1e-999", "number"),
        ("0.1234567890123456789", "number"),
        ([], "number"),
        ("TRUE", "boolean"),
        (1, "boolean"),
        ({}, "string"),
        ([], "string"),
        ("9" * 5000, "integer"),
        ("1e" + "9" * 100, "number"),
    ],
)
def test_invalid_or_lossy_conversions(value, mode):
    with pytest.raises(ProjectionError):
        project(value, mode)


def test_escaped_pointers_arrays_and_shared_parent():
    row = parse_dataset(b'[{"a/b":{"~":["zero", "one"]},"":"empty"}]', "json").rows[0]
    output = project_row(
        row,
        plan(
            [
                {"source": "/a~1b/~0/1", "target": "/nested/a~1b"},
                {"source": "/a~1b/~0/0", "target": "/nested/~0"},
                {"source": "/", "target": "/"},
            ]
        ),
    )
    assert output.values == {"nested": {"a/b": "one", "~": "zero"}, "": "empty"}


@pytest.mark.parametrize(
    "source,target",
    [
        ("raw", "/value"),
        ("/raw~2", "/value"),
        ("/raw", "value"),
        ("/raw", "/value~"),
        ("/" + "/".join(["x"] * 33), "/value"),
        ("/raw", "/" + "/".join(["x"] * 33)),
    ],
)
def test_invalid_pointers(source, target):
    row = parse_dataset(b'[{"raw":1}]', "json").rows[0]
    with pytest.raises(ProjectionError):
        project_row(row, plan([{"source": source, "target": target}]))


@pytest.mark.parametrize("first,second", [("/a", "/a"), ("/a", "/a/b"), ("/a/b", "/a")])
def test_overlap_rejected(first, second):
    row = parse_dataset(b'[{"raw":1}]', "json").rows[0]
    with pytest.raises(ProjectionError, match="Overlapping"):
        project_row(
            row,
            plan(
                [
                    {"source": "/raw", "target": first},
                    {"source": "/raw", "target": second},
                ]
            ),
        )


@pytest.mark.parametrize("pointer", ["/missing", "/raw/2", "/raw/01", "/raw/-", "/raw/0/x"])
def test_missing_sources_do_not_become_null(pointer):
    row = parse_dataset(b'[{"raw":[1]}]', "json").rows[0]
    with pytest.raises(ProjectionError, match="missing"):
        project_row(row, plan([{"source": pointer, "target": "/value"}]))
    assert row.values == {"raw": [1]}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "\ud800"])
def test_nonfinite_or_invalid_unicode_row_rejected(value):
    row = SourceRow(1, "/0", None, None, json.dumps({"raw": value}))
    with pytest.raises(ProjectionError):
        project_row(row, plan([{"source": "/raw", "target": "/value"}]))


@pytest.mark.parametrize(
    "spec",
    [
        {"fields": []},
        {"version": True, "fields": [{"source": "/a", "target": "/b"}]},
        {"version": "2", "fields": [{"source": "/a", "target": "/b"}]},
        {"fields": [{"source": "/a", "target": "/b", "conversion": "guess"}]},
        {"fields": [{"source": "/a", "target": "/b", "extra": 1}]},
        {"fields": [{"source": "/a", "target": "/b"}] * 101},
    ],
)
def test_invalid_plans(spec):
    with pytest.raises(ValidationError):
        ProjectionPlan.model_validate(spec)
