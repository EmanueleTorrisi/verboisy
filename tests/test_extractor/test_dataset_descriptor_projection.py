# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal descriptors preserve captured values and never infer semantic agreement."""

import json
from dataclasses import FrozenInstanceError, asdict

import pytest
from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.extractor.descriptor_projection import project_descriptor
from verboisy.extractor.projection import ProjectionError


def row(value, label):
    return parse_dataset(json.dumps([{"value": value, "label": label}]).encode(), "json").rows[0]


@pytest.mark.parametrize("kind", ["definition", "methodology"])
@pytest.mark.parametrize("value", [2, "002", None, True, 2.5, {"x": [1, None]}])
def test_exact_typed_values_literal_labels_and_immutable_derivations(kind, value):
    source = row(value, "  Résidents\n通常人口 — v2.  ")
    before = source.values_json
    result = project_descriptor(source, "/value", "/label", kind=kind)
    assert result.value == value
    assert result.observed_label == "  Résidents\n通常人口 — v2.  "
    assert json.loads(result.descriptor_value_json) == result.observed_label
    assert result.kind == kind and result.value_pointer == "/value"
    assert result.descriptor_pointer == "/label"
    assert asdict(result)["policy_version"] == "1"
    assert source.values_json == before
    with pytest.raises(FrozenInstanceError):
        result.observed_label = "changed"
    if isinstance(value, dict):
        copied = result.value
        copied["x"].append(99)
        assert result.value == value


@pytest.mark.parametrize("label", [None, 2, True, [], {}, "", " \t\n", "x" * 501])
def test_missing_nontext_blank_and_oversized_labels_are_not_grounded(label):
    with pytest.raises(ProjectionError, match="nonblank label"):
        project_descriptor(row(2, label), "/value", "/label", kind="definition")


def test_unicode_label_boundary_and_different_literals_remain_distinct():
    first = project_descriptor(row(2, "人" * 500), "/value", "/label", kind="definition")
    assert first.observed_label == "人" * 500
    labels = ["Census", "census", " Census ", "Survey", "=1+1"]
    assert [
        project_descriptor(row(2, label), "/value", "/label", kind="methodology").observed_label
        for label in labels
    ] == labels


@pytest.mark.parametrize(
    "fmt,body",
    [
        ("csv", b'value,label\r\n2,"Census\n2025"\r\n'),
        ("json", b'[{"value":2,"label":"Census\\n2025"}]'),
        ("jsonl", b'\n{"value":2,"label":"Census\\n2025"}\n'),
    ],
)
def test_source_bytes_physical_locations_and_repeated_replay(fmt, body):
    data = parse_dataset(body, fmt)
    source = data.rows[0]
    first = project_descriptor(source, "/value", "/label", kind="methodology")
    assert first == project_descriptor(source, "/value", "/label", kind="methodology")
    assert first.observed_label == "Census\n2025"
    assert (first.row_index, first.source_pointer, first.line_start, first.line_end) == (
        source.row_index,
        source.source_pointer,
        source.line_start,
        source.line_end,
    )
    assert data.original_bytes == body


def test_escaped_nested_array_pointers_and_same_row_binding():
    data = parse_dataset(
        b'[{"a/b":[{"~value":2,"label":"A"}]},{"a/b":[{"~value":3,"label":"B"}]}]',
        "json",
    )
    results = [
        project_descriptor(source, "/a~1b/0/~0value", "/a~1b/0/label", kind="definition")
        for source in data.rows
    ]
    assert [(result.value, result.observed_label, result.row_index) for result in results] == [
        (2, "A", 1),
        (3, "B", 2),
    ]


@pytest.mark.parametrize(
    "value_pointer,descriptor_pointer",
    [
        ("value", "/label"),
        ("/value", "label"),
        ("/bad~2", "/label"),
        ("/value", "/bad~2"),
        ("/missing", "/label"),
        ("/value", "/missing"),
        ("/" + "/".join(["x"] * 33), "/label"),
        ("/value", "/" + "/".join(["x"] * 33)),
    ],
)
def test_invalid_missing_and_deep_pointers_fail(value_pointer, descriptor_pointer):
    with pytest.raises(ProjectionError):
        project_descriptor(row(2, "Census"), value_pointer, descriptor_pointer, kind="definition")


@pytest.mark.parametrize("kind", ["unit", "quality", "", None])
def test_unsupported_descriptor_kinds_fail(kind):
    with pytest.raises(ProjectionError, match="Unsupported"):
        project_descriptor(row(2, "Census"), "/value", "/label", kind=kind)


@pytest.mark.parametrize(
    "payload",
    ['{"value":Infinity,"label":"Census"}', '{"value":2,"label":"\\ud800"}'],
)
def test_manual_nonfinite_or_invalid_utf8_rows_cannot_emit_derivations(payload):
    source = SourceRow(1, "/0", None, None, payload)
    with pytest.raises(ProjectionError, match="finite UTF-8 JSON"):
        project_descriptor(source, "/value", "/label", kind="methodology")
