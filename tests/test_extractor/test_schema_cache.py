# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Compiled-model reuse must preserve the uncached contract's decisions."""

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from verboisy.extractor import schema_cache
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.utils.exceptions import ExtractionError


@pytest.fixture(autouse=True)
def isolated_cache():
    schema_cache._compile.cache_clear()
    yield
    schema_cache._compile.cache_clear()


SCHEMA = {
    "type": "object",
    "properties": {"amount": {"type": "integer", "minimum": 0}},
    "required": ["amount"],
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "schema,records",
    [
        (SCHEMA, [{"amount": 0}, {"amount": -1}, {"amount": "1"}, {}, {"amount": True}]),
        ({"type": "array", "items": SCHEMA}, [{"amount": 2}, {"amount": 1.5}]),
        ({"amount": {"type": ["number", "null"]}}, [{"amount": None}, {"amount": 2.5}]),
        (
            {
                "type": "object",
                "$defs": {"positive": {"type": "integer", "minimum": 1}},
                "properties": {"amount": {"$ref": "#/$defs/positive"}},
            },
            [{"amount": 1}, {"amount": 0}],
        ),
        (
            {"properties": {"date": {"type": "string", "format": "date"}}},
            [{"date": "2026-10-08"}, {"date": "invalid"}],
        ),
        (
            {"properties": {"model_dump": {"const": "李雷"}, "_name": {"type": "string"}}},
            [{"model_dump": "李雷", "_name": "Anaïs"}, {"model_dump": "different"}],
        ),
        (
            {"properties": {"amount": {"enum": [0, 1.5, None, False]}}},
            [{"amount": 1.5}, {"amount": 7}],
        ),
    ],
)
def test_cached_and_uncached_validation_decisions_match(schema, records):
    reference = SchemaBuilder.build_model("Record", schema)
    for record in records:
        try:
            reference.model_validate(record)
        except ValueError:
            with pytest.raises(ValueError):
                schema_cache.validate_record(record, schema)
        else:
            schema_cache.validate_record(record, schema)
    assert schema_cache._compile.cache_info().misses == 1


def test_reuse_still_validates_each_record_and_schema_mutation():
    schema = copy.deepcopy(SCHEMA)
    schema_cache.validate_record({"amount": 1}, schema)
    schema_cache.validate_record({"amount": 2}, copy.deepcopy(schema))
    assert schema_cache._compile.cache_info().hits == 1
    with pytest.raises(ValueError):
        schema_cache.validate_record({"amount": -1}, schema)
    schema["properties"]["amount"]["minimum"] = 5
    with pytest.raises(ValueError):
        schema_cache.validate_record({"amount": 2}, schema)
    schema_cache.validate_record({"amount": 2}, SCHEMA)
    assert schema_cache._compile.cache_info().currsize == 2


def test_cache_evicts_old_models_and_recompiles_same_decision():
    for index in range(schema_cache.MAX_CACHED_SCHEMAS + 1):
        schema_cache.validate_record({"amount": 1}, {**SCHEMA, "title": str(index)})
    info = schema_cache._compile.cache_info()
    assert info.currsize == schema_cache.MAX_CACHED_SCHEMAS
    with pytest.raises(ValueError):
        schema_cache.validate_record({"amount": -1}, {**SCHEMA, "title": "0"})
    assert schema_cache._compile.cache_info().misses == info.misses + 1


@pytest.mark.parametrize(
    "schema",
    [
        {**SCHEMA, "description": "x" * schema_cache.MAX_SCHEMA_BYTES},
        {"properties": {"amount": {"const": (1, 2)}}},
        {"properties": {"amount": {"const": {1: "value"}}}},
    ],
)
def test_oversized_and_non_json_schemas_keep_original_path(schema):
    record = {"amount": 1}
    try:
        SchemaBuilder.build_model("Record", schema).model_validate(record)
    except (ExtractionError, ValueError) as error:
        with pytest.raises(type(error)):
            schema_cache.validate_record(record, schema)
    else:
        schema_cache.validate_record(record, schema)
    assert schema_cache._compile.cache_info().currsize == 0


@pytest.mark.parametrize(
    "schema",
    [
        {"properties": {"amount": {"minimum": float("nan")}}},
        {"properties": {"amount": {"type": "unknown"}}},
        {"$ref": "https://example.invalid/schema"},
    ],
)
def test_invalid_schemas_never_become_cached_successes(schema):
    for _ in range(2):
        with pytest.raises(ExtractionError):
            schema_cache.validate_record({"amount": 1}, schema)
    assert schema_cache._compile.cache_info().currsize == 0


def test_threads_validate_independent_records():
    schema_cache.validate_record({"amount": 1}, SCHEMA)

    def accepted(value):
        try:
            schema_cache.validate_record({"amount": value}, SCHEMA)
        except ValueError:
            return False
        return True

    values = [0, -1, 4, "4", None] * 8
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(accepted, values)) == [True, False, True, False, False] * 8


def test_verifier_cache_does_not_skip_record_or_grounding_checks(monkeypatch):
    from verboisy.evidence import verify as verifier
    from verboisy.evidence.models import TaskSpec

    from benchmarks.workloads import SCHEMA as FIXTURE_SCHEMA
    from benchmarks.workloads import evidence, records

    page, valid = evidence(records(1)[0], 0)
    invalid_type = valid.model_copy(deep=True)
    invalid_type.record["amount"] = "invalid"
    invalid_quote = valid.model_copy(deep=True)
    invalid_quote.evidence["/name"].quote = "unobserved quote"
    invalid_scope = valid.model_copy(deep=True)
    invalid_scope.scope = "outside"
    candidates = [valid, invalid_type, invalid_quote, invalid_scope]
    task = TaskSpec(identity_fields=["/name"])
    cached = [verifier.verify(candidate, page, FIXTURE_SCHEMA, task) for candidate in candidates]
    assert cached[0] == []
    assert cached[1] == ["schema_invalid"]
    assert cached[2] and cached[3]
    assert schema_cache._compile.cache_info().hits == 3
    monkeypatch.setattr(
        verifier,
        "validate_record",
        lambda record, schema: SchemaBuilder.build_model("Record", schema).model_validate(record),
    )
    assert cached == [
        verifier.verify(candidate, page, FIXTURE_SCHEMA, task) for candidate in candidates
    ]
