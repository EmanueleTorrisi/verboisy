# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit capabilities preserve source values and distinguish opaque capture from parsing."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.dataset_formats import format_capabilities
from verboisy.extractor.dataset import DatasetParseError, parse_dataset


@pytest.mark.parametrize("body", [b"", b"\xff\x00", b"PK\x03\x04payload", b"%PDF-1.7", b"\x1f\x8b"])
def test_asset_indexes_any_immutable_bytes(body):
    parsed = parse_dataset(body, "asset")
    assert parsed.original_bytes == body
    assert parsed.rows[0].source_pointer == "/"
    assert parsed.rows[0].values == {
        "sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body),
    }
    with pytest.raises(DatasetParseError, match="row limit"):
        parse_dataset(body, "asset", max_rows=0)


def test_tsv_preserves_quoted_newlines_and_formula_text():
    parsed = parse_dataset('name\tnote\r\nAnaïs\t"one\ntwo"\r\n李雷\t=1+1\r\n'.encode(), "tsv")
    assert [r.values for r in parsed.rows] == [
        {"name": "Anaïs", "note": "one\ntwo"},
        {"name": "李雷", "note": "=1+1"},
    ]
    assert [(r.line_start, r.line_end) for r in parsed.rows] == [(2, 3), (4, 4)]


def test_text_preserves_blank_lines_unicode_and_physical_locations():
    parsed = parse_dataset("Anaïs\r\n\r\n李雷\rFinal".encode(), "text")
    assert [r.values for r in parsed.rows] == [{"text": v} for v in ["Anaïs", "", "李雷", "Final"]]
    assert [r.line_start for r in parsed.rows] == [1, 2, 3, 4]
    with pytest.raises(DatasetParseError, match="row limit"):
        parse_dataset(b"a\nb", "text", max_rows=1)


def test_registry_and_cli_inspection_make_no_configuration_or_provider_requests(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("inspection must not initialise a run"))
    monkeypatch.setattr("verboisy.cli.main.Settings", forbidden)
    result = CliRunner().invoke(app, ["formats"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report == format_capabilities()
    assert len(report["formats"]) == 8
    assert not report["automatic_format_detection"]
    assert all(not f["model_assisted_extraction"] for f in report["formats"])
    assert {
        f["format"] for f in report["formats"] if f["support_level"] == "capture_and_index"
    } == {"asset"}
    forbidden.assert_not_called()


def test_capabilities_distinguish_large_dataset_and_time_series_workflows():
    from verboisy.streaming.contract import FORMATS

    report = format_capabilities()
    assert {f["format"] for f in report["formats"] if f["streaming_input"]} == FORMATS
    assert report["large_dataset_preparation"]["input_formats"] == sorted(FORMATS)
    assert set(report["large_dataset_preparation"]["output_formats"]) == {"csv", "json", "jsonl"}
    assert report["large_dataset_preparation"]["model_requests"] == 0
    assert not report["time_series"]["streaming_analysis"]
    assert not report["time_series"]["interpolation"]


def test_unknown_format_is_rejected_before_interpreting_bytes():
    with pytest.raises(DatasetParseError, match="Unsupported dataset format"):
        parse_dataset(b"%PDF-1.7", "pdf")
