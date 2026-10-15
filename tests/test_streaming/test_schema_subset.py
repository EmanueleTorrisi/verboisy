# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Unsupported collection predicates fail before creating a streaming ledger."""

from contextlib import closing

import pytest
from verboisy.streaming import StreamLedger, stream_dataset
from verboisy.streaming.contract import StreamError
from verboisy.utils.config import Settings


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("minItems", 2),
        ("maxItems", 1),
        ("uniqueItems", True),
        ("contains", {"const": 42}),
        ("minContains", 1),
        ("maxContains", 1),
        ("prefixItems", []),
        ("unevaluatedItems", False),
        ("allOf", []),
        ("anyOf", []),
        ("oneOf", []),
        ("if", True),
        ("then", False),
        ("else", True),
        ("$ref", "#/$defs/x"),
        ("$dynamicRef", "#x"),
    ],
)
def test_unsupported_array_keywords_no_database(tmp_path, keyword, value):
    source = tmp_path / "source"
    source.write_text('{"n":1}\n')
    schema = {"type": "array", "items": {"type": "object"}, keyword: value}
    with pytest.raises(StreamError, match="individual rows"):
        stream_dataset(
            database=tmp_path / "stream.db",
            source=source,
            dataset_format="jsonl",
            schema=schema,
            config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
        )
    assert not (tmp_path / "stream.db").exists()


def test_pure_items_keep_root_reference_context(tmp_path):
    source = tmp_path / "source"
    source.write_text('{"n":1}\n')
    schema = {
        "type": "array",
        "$defs": {"number": {"type": "integer"}},
        "items": {"type": "object", "properties": {"n": {"$ref": "#/$defs/number"}}},
    }
    result = stream_dataset(
        database=tmp_path / "stream.db",
        source=source,
        dataset_format="jsonl",
        schema=schema,
        config=Settings(_env_file=None, dataset_local_roots=[str(tmp_path)]),
    )
    assert result.status == "COMPLETED"
    with closing(StreamLedger(tmp_path / "stream.db", read_only=True)) as ledger:
        assert ledger.page(result.job_id)[0]["record"] == {"n": 1}


@pytest.mark.parametrize("schema", [False, True, []])
def test_invalid_top_level_schema_type_does_not_create_state(tmp_path, schema):
    with pytest.raises(StreamError, match="JSON object"):
        stream_dataset(
            database=tmp_path / "stream.db",
            source=tmp_path / "source",
            dataset_format="jsonl",
            schema=schema,
        )
    assert not (tmp_path / "stream.db").exists()
