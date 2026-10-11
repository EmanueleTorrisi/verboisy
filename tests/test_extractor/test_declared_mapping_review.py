# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit conversion plans are reviewed verbatim and validated on every source row."""

import json
from dataclasses import replace

import pytest
from verboisy.evidence.models import ProjectionPlan
from verboisy.extractor.dataset import parse_dataset
from verboisy.extractor.mapping import SchemaMappingError, declared_mapping, validate_mapping
from verboisy.extractor.profile import profile_dataset
from verboisy.extractor.review import review_mapping
from verboisy.storage.research import ResearchStore
from verboisy.utils.exceptions import VerboisyError

from tests.test_extractor import test_mapping_review as fixtures

saved = fixtures.saved
command = fixtures.command


@pytest.mark.parametrize(
    "conversion,value,expected,kind",
    [
        ("integer", "22", 22, "integer"),
        ("number", "2.5", 2.5, "number"),
        ("boolean", "true", True, "boolean"),
        ("string", 22, "22", "string"),
        ("date_dmy", "03/04/2025", "2025-04-03", "string"),
    ],
)
def test_explicit_conversions_bound_and_validated(conversion, value, expected, kind):
    data = parse_dataset(json.dumps([{"raw": value, "unused": 1}]).encode(), "json")
    profile = profile_dataset(data)
    schema = {"type": "object", "properties": {"target": {"type": kind}}, "required": ["target"]}
    plan = ProjectionPlan.model_validate(
        {"fields": [{"source": "/raw", "target": "/target", "conversion": conversion}]}
    )
    suggestion = declared_mapping(profile, schema, plan)
    assert suggestion.asset_sha256 == data.sha256
    assert suggestion.decisions[0].basis == "declared_plan"
    assert suggestion.decisions[0].status == "declared"
    assert suggestion.unmapped_profile_pointers == ("/unused",)
    assert validate_mapping(data, schema, suggestion) == plan
    from verboisy.extractor.projection import project_row

    assert project_row(data.rows[0], plan).values == {"target": expected}


def test_explicit_plan_can_use_complex_schema_with_full_validation():
    data = parse_dataset(b'[{"raw":"22"}]', "json")
    schema = {
        "type": "object",
        "properties": {"age": {"oneOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}},
        "required": ["age"],
    }
    plan = ProjectionPlan.model_validate(
        {"fields": [{"source": "/raw", "target": "/age", "conversion": "integer"}]}
    )
    profile = profile_dataset(data)
    assert validate_mapping(data, schema, declared_mapping(profile, schema, plan)) == plan
    with pytest.raises(SchemaMappingError, match="profile"):
        declared_mapping(replace(profile, profile_version="unknown"), schema, plan)


@pytest.mark.parametrize("conversion", ["identity", "integer", "date_iso"])
def test_declared_conversion_failure_blocks_cli_approval(tmp_path, saved, conversion):
    db, rid, aid = saved
    projection = tmp_path / "input.json"
    # Missing target, invalid integer, and invalid date all produce an auditable blocked request.
    projection.write_text(
        json.dumps(
            {
                "fields": [
                    {
                        "source": "/name",
                        "target": "/other" if conversion == "identity" else "/name",
                        "conversion": conversion,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    result = command(
        saved, output, "--projection", str(projection), "--plan", str(tmp_path / "approved.json")
    )
    assert result.exit_code == 2, result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "blocked" and report["proposal_kind"] == "declared_plan"
    assert (
        report["suggestion"]["plan_json"]
        == ProjectionPlan.model_validate_json(
            projection.read_text(encoding="utf-8")
        ).model_dump_json()
    )
    store = ResearchStore(str(db))
    assert store.events(rid, "dataset_mapping_review")[-1]["payload"] == report
    store.close()
    assert not (tmp_path / "approved.json").exists()


@pytest.mark.parametrize("approve", [False, True])
def test_cli_explicit_plan_report_and_optional_approval(tmp_path, saved, approve):
    projection = tmp_path / "input.json"
    projection.write_text(
        '{"fields":[{"source":"/name","target":"/name","conversion":"string"}]}', encoding="utf-8"
    )
    before = projection.read_bytes()
    output = tmp_path / "report.json"
    result = command(
        saved,
        output,
        "--projection",
        str(projection),
        *(["--plan", str(tmp_path / "approved.json")] if approve else []),
    )
    assert result.exit_code == 0, result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == ("approved" if approve else "proposed")
    assert report["suggestion"]["decisions"][0]["basis"] == "declared_plan"
    assert report["plan"]["fields"][0]["conversion"] == "string"
    assert projection.read_bytes() == before
    assert (tmp_path / "approved.json").exists() == approve


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{},{}",
        b'{"fields":[],"fields":[]}',
        b'{"fields":[]}',
        b'{"version":"2","fields":[{"source":"/name","target":"/name"}]}',
    ],
)
def test_invalid_declared_plan_does_not_write_report(tmp_path, saved, data):
    projection = tmp_path / "input.json"
    projection.write_bytes(data)
    result = command(saved, tmp_path / "report.json", "--projection", str(projection))
    assert result.exit_code == 1
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("kind", ["both", "output", "plan"])
def test_explicit_input_overlap_and_conflicting_aliases(tmp_path, saved, kind):
    db, rid, aid = saved
    projection = tmp_path / "input.json"
    projection.write_text('{"fields":[{"source":"/name","target":"/name"}]}', encoding="utf-8")
    kwargs = {"projection_path": projection}
    if kind == "both":
        kwargs["aliases_path"] = tmp_path / "aliases.json"
    if kind == "plan":
        kwargs["plan_path"] = projection
    with pytest.raises(VerboisyError):
        review_mapping(
            db, rid, aid, projection if kind == "output" else tmp_path / "report.json", **kwargs
        )


def test_explicit_plan_after_sample_can_fail(tmp_path):
    data = parse_dataset(json.dumps([{"raw": "22"}] * 1000 + [{"raw": "unknown"}]).encode(), "json")
    plan = ProjectionPlan.model_validate(
        {"fields": [{"source": "/raw", "target": "/age", "conversion": "integer"}]}
    )
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
    suggestion = declared_mapping(profile_dataset(data), schema, plan)
    assert suggestion.profile_incomplete
    with pytest.raises(SchemaMappingError, match="full-row"):
        validate_mapping(data, schema, suggestion)
