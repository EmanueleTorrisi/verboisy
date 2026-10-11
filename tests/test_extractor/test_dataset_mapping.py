# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Mapping proposals never hide ambiguity, sampled gaps or schema failures."""

import json
from dataclasses import FrozenInstanceError, replace

import pytest
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.mapping import SchemaMappingError, suggest_mapping, validate_mapping
from verboisy.extractor.profile import profile_dataset
from verboisy.extractor.projection import project_row


def source(rows):
    return parse_dataset(json.dumps(rows, ensure_ascii=False).encode(), "json")


def schema(fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def propose(rows, fields, **kwargs):
    data = source(rows)
    target = schema(fields)
    return data, target, suggest_mapping(profile_dataset(data), target, **kwargs)


def test_exact_nested_escaped_mapping_and_transparent_drops():
    data, target, suggestion = propose(
        [
            {"person": {"name": "Anaïs", "unused": 1}, "a/b": True, "extra": "discard"},
        ],
        {"person": schema({"name": {"type": "string"}}), "a/b": {"type": "boolean"}},
    )
    assert suggestion.plan is not None
    assert [d.source for d in suggestion.decisions] == ["/person/name", "/a~1b"]
    assert all(d.basis == "exact" and d.status == "suggested" for d in suggestion.decisions)
    assert suggestion.unmapped_profile_pointers == ("/person/unused", "/extra")
    plan = validate_mapping(data, target, suggestion)
    assert project_row(data.rows[0], plan).values == {"person": {"name": "Anaïs"}, "a/b": True}
    assert data.rows[0].values["extra"] == "discard"
    assert suggestion.plan is not suggestion.plan
    with pytest.raises(FrozenInstanceError):
        suggestion.plan_json = None


def test_unique_explicit_alias_and_exact_precedence():
    data, target, suggestion = propose(
        [{"Name": "李雷", "Age": 22}],
        {"name": {"type": "string"}, "years": {"type": "integer"}},
        aliases={"/name": ["/Name", "/Name"], "/years": ["/Age"]},
    )
    assert suggestion.decisions[0].basis == "caller_alias"
    assert validate_mapping(data, target, suggestion)
    _, _, exact = propose(
        [{"name": "exact", "Name": "alias"}],
        {"name": {"type": "string"}},
        aliases={"/name": ["/Name"]},
    )
    assert exact.decisions[0].source == "/name"
    assert exact.decisions[0].basis == "exact"


@pytest.mark.parametrize(
    "rows,fields,aliases,status",
    [
        ([{"Name": "A"}], {"name": {"type": "string"}}, None, "unobserved"),
        (
            [{"Name": "A", "Person": "B"}],
            {"name": {"type": "string"}},
            {"/name": ["/Name", "/Person"]},
            "ambiguous",
        ),
        ([{"years": "31"}], {"years": {"type": "integer"}}, None, "incompatible_types"),
        ([{"years": True}], {"years": {"type": "integer"}}, None, "incompatible_types"),
        (
            [{"years": 31}, {"years": "31"}],
            {"years": {"type": "integer"}},
            None,
            "incompatible_types",
        ),
        ([{"name": "A"}, {}], {"name": {"type": "string"}}, None, "missing_values"),
        ([{"name": None}], {"name": {"type": "string"}}, None, "incompatible_types"),
        ([{"name": "A"}], {"name": {}}, None, "unsupported_schema"),
        ([{"name": "A"}], {"name": True}, None, "unsupported_schema"),
        ([{"name": "A"}], {"name": {"anyOf": [{"type": "string"}]}}, None, "unsupported_schema"),
    ],
)
def test_unresolved_cases(rows, fields, aliases, status):
    data, target, suggestion = propose(rows, fields, aliases=aliases)
    assert suggestion.decisions[0].status == status
    assert suggestion.plan is None
    with pytest.raises(SchemaMappingError, match="unresolved"):
        validate_mapping(data, target, suggestion)


@pytest.mark.parametrize(
    "value,types",
    [
        (1, "number"),
        (1.5, "number"),
        (None, ["integer", "null"]),
        ([], "array"),
        ({}, "object"),
        ("=1+1", "string"),
    ],
)
def test_identity_only_compatible_types(value, types):
    data, target, suggestion = propose([{"value": value}], {"value": {"type": types}})
    plan = validate_mapping(data, target, suggestion)
    assert plan.fields[0].conversion == "identity"
    assert project_row(data.rows[0], plan).values == {"value": value}


def test_array_root_schema_and_nested_items_are_validated():
    data = source([{"values": [1, 2]}])
    target = {
        "type": "array",
        "items": schema({"values": {"type": "array", "items": {"type": "integer"}}}),
    }
    suggestion = suggest_mapping(profile_dataset(data), target)
    assert validate_mapping(data, target, suggestion)
    bad = source([{"values": ["wrong"]}])
    bad_suggestion = suggest_mapping(profile_dataset(bad), target)
    assert bad_suggestion.plan is not None
    with pytest.raises(SchemaMappingError, match="full-row"):
        validate_mapping(bad, target, bad_suggestion)


@pytest.mark.parametrize("last", [{"age": "wrong"}, {}, {"age": -1}])
def test_unsampled_rows_are_not_assumed_valid(last):
    data = source([{"age": 31}, last])
    target = schema({"age": {"type": "integer", "minimum": 0}})
    suggestion = suggest_mapping(profile_dataset(data, sample_rows=1), target)
    assert suggestion.profile_incomplete
    assert suggestion.plan is not None
    with pytest.raises(SchemaMappingError, match="full-row"):
        validate_mapping(data, target, suggestion)


@pytest.mark.parametrize(
    "value,definition",
    [
        ("not-a-date", {"type": "string", "format": "date"}),
        ("EUR 12", {"type": "number"}),
        ("other", {"type": "string", "enum": ["allowed"]}),
    ],
)
def test_dates_currency_and_constraints_are_not_guessed(value, definition):
    data, target, suggestion = propose([{"value": value}], {"value": definition})
    with pytest.raises(SchemaMappingError):
        validate_mapping(data, target, suggestion)


@pytest.mark.parametrize("mutation", ["asset", "schema", "policy"])
def test_bindings(mutation):
    data, target, suggestion = propose([{"name": "A"}], {"name": {"type": "string"}})
    if mutation == "asset":
        suggestion = replace(suggestion, asset_sha256="wrong")
    elif mutation == "schema":
        target = schema({"name": {"type": "string", "minLength": 3}})
    else:
        suggestion = replace(suggestion, policy_version="2")
    with pytest.raises(SchemaMappingError, match="binding"):
        validate_mapping(data, target, suggestion)


@pytest.mark.parametrize(
    "aliases",
    [
        {"/other": ["/Name"]},
        {"/name": "/Name"},
        {"/name": []},
        {"/name": ["/Name"] * 101},
        {"/name": [1]},
        {"/name": ["x"]},
        {"/name": ["/bad~2"]},
        {"/name": ["/" + "x" * 8192]},
    ],
)
def test_invalid_aliases(aliases):
    with pytest.raises(SchemaMappingError, match="alias"):
        propose([{"Name": "A"}], {"name": {"type": "string"}}, aliases=aliases)


@pytest.mark.parametrize(
    "target",
    [
        schema({}),
        {
            "type": "object",
            "$ref": "#/$defs/record",
            "$defs": {"record": schema({"name": {"type": "string"}})},
        },
        {"type": "object", "properties": {"name": {"type": "string"}}, "allOf": [{}]},
    ],
)
def test_unsupported_schema_remains_explicit(target):
    suggestion = suggest_mapping(profile_dataset(source([{"name": "A"}])), target)
    assert suggestion.decisions[0].status == "unsupported_schema"
    assert suggestion.plan is None


def test_invalid_schema_and_mapping_limits():
    with pytest.raises(SchemaMappingError, match="Invalid target schema"):
        suggest_mapping(profile_dataset(source([])), {"type": "string"})
    for target in [
        schema({str(i): {"type": "string"} for i in range(101)}),
        schema({"x" * 8192: {"type": "string"}}),
    ]:
        with pytest.raises(SchemaMappingError, match="limits"):
            suggest_mapping(profile_dataset(source([])), target)
    deep = {"type": "string"}
    for _ in range(33):
        deep = schema({"x": deep})
    with pytest.raises(SchemaMappingError, match="limits"):
        suggest_mapping(profile_dataset(source([])), deep)


def test_empty_profile_and_truncation_are_not_global_absence_claims():
    data = source([])
    target = schema({"name": {"type": "string"}})
    suggestion = suggest_mapping(profile_dataset(data), target)
    assert suggestion.decisions[0].status == "unobserved"
    with pytest.raises(SchemaMappingError):
        validate_mapping(data, target, suggestion)
    full = source([{"extra": 1, "name": "A"}])
    capped = suggest_mapping(profile_dataset(full, max_fields=1), target)
    assert capped.profile_incomplete
    assert capped.decisions[0].status == "unobserved"
    # A complete-looking externally constructed plan still cannot validate an empty capture.
    valid = suggest_mapping(profile_dataset(source([{"name": "A"}])), target)
    empty_bound = replace(valid, asset_sha256=data.sha256)
    with pytest.raises(SchemaMappingError, match="empty"):
        validate_mapping(data, target, empty_bound)


def test_invalid_profile_version_unicode_schema_and_alias_container():
    profile = profile_dataset(source([{"name": "A"}]))
    with pytest.raises(SchemaMappingError, match="profile version"):
        suggest_mapping(replace(profile, profile_version="2"), schema({"name": {"type": "string"}}))
    with pytest.raises(SchemaMappingError, match="UTF-8"):
        suggest_mapping(profile, schema({"name": {"type": "string", "description": "\ud800"}}))
    with pytest.raises(SchemaMappingError, match="alias"):
        suggest_mapping(profile, schema({"name": {"type": "string"}}), aliases={"/name": None})
