# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared file capabilities shared by tasks, acquisition, inspection and parsers."""

from typing import Any, Literal

DatasetFormat = Literal["csv", "json", "jsonl", "tsv", "text", "docx", "xlsx", "asset"]

MIME_TYPES: dict[str, tuple[str, ...]] = {
    "csv": ("text/csv", "application/csv", "text/plain", "application/octet-stream"),
    "json": ("application/json", "text/plain", "application/octet-stream"),
    "jsonl": (
        "application/x-ndjson",
        "application/jsonl",
        "text/plain",
        "application/octet-stream",
    ),
    "tsv": ("text/tab-separated-values", "text/plain", "application/octet-stream"),
    "text": ("text/plain", "text/markdown", "application/octet-stream"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    ),
    "asset": ("application/octet-stream",),
}


def format_capabilities() -> dict[str, Any]:
    """Report implemented contracts without inferring extraction from an extension."""
    from verboisy.streaming.contract import FORMATS

    outputs = {
        "csv": "Exact header-keyed string records",
        "json": "Array of object records with JSON types",
        "jsonl": "Object records with physical line locations",
        "tsv": "Exact header-keyed string records",
        "text": "Physical-line records with a text field",
        "docx": "Main-body paragraph records with a text field; no OCR or layout reconstruction",
        "xlsx": (
            "Worksheet records with sheet and values fields; explicit first-row headers; "
            "no formulas or date-style inference"
        ),
        "asset": "Byte-count and SHA-256 index record; content is captured, not interpreted",
    }
    return {
        "capability_version": "1",
        "formats": [
            {
                "format": name,
                "support_level": "capture_and_index" if name == "asset" else "deterministic_parse",
                "output": outputs[name],
                "media_types": list(media),
                "model_assisted_extraction": False,
                "streaming_input": name in FORMATS,
            }
            for name, media in MIME_TYPES.items()
        ],
        "automatic_format_detection": False,
        "arbitrary_file_capture_format": "asset",
        "large_dataset_preparation": {
            "command": "verboisy stream",
            "input_formats": sorted(FORMATS),
            "output_formats": ["csv", "json", "jsonl"],
            "result_materialization": "bounded pages, counts and disk-backed exports",
            "resume": "saved byte capture and committed row checkpoints",
            "model_requests": 0,
            "global_sorting_or_grouping": False,
        },
        "time_series": {
            "workflow": "explicit policy on accepted research records",
            "timestamp_policy_required": True,
            "diagnostics": [
                "invalid_timestamp",
                "invalid_series",
                "duplicate_instant",
                "missing_observations",
                "off_grid_intervals",
            ],
            "interpolation": False,
            "streaming_analysis": False,
        },
    }
