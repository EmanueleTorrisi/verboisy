# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Rule reuse remains local and never bypasses mapping or grounding decisions."""

import json

import pytest
from verboisy.evidence import verify as verifier
from verboisy.evidence.models import FieldRule, TaskSpec

from benchmarks.workloads import SCHEMA, evidence, records


def test_default_rule_created_once_per_call_and_never_for_explicit_rules(monkeypatch):
    page, candidate = evidence(records(1)[0], 0)
    created = []

    def make_rule():
        rule = FieldRule()
        created.append(rule)
        return rule

    monkeypatch.setattr(verifier, "FieldRule", make_rule)
    assert verifier.verify(candidate, page, SCHEMA, TaskSpec()) == []
    assert len(created) == 1
    # A later call gets a fresh rule even if a retained previous one was mutated.
    created[0].source = "page_url"
    assert verifier.verify(candidate, page, SCHEMA, TaskSpec()) == []
    assert len(created) == 2
    assert created[0] is not created[1]
    explicit = TaskSpec(field_rules={p: FieldRule() for p in candidate.evidence})
    assert verifier.verify(candidate, page, SCHEMA, explicit) == []
    assert len(created) == 2


@pytest.mark.parametrize("value", ["normalized", 42, True, None])
def test_json_mapping_keys_keep_original_semantics(value):
    page, candidate = evidence(records(1)[0], 0)
    proof = candidate.evidence["/name"]
    candidate.record["name"] = value
    schema = {"type": "object", "properties": {"name": {}}, "additionalProperties": True}
    rule = FieldRule(mapping={json.dumps(value, ensure_ascii=False): proof.quote})
    task = TaskSpec(allow_nulls=False, field_rules={"/name": rule})
    assert verifier.verify(candidate, page, schema, task) == []
    rule.mapping[json.dumps(value, ensure_ascii=False)] = "unobserved replacement"
    assert verifier.verify(candidate, page, schema, task) == ["/name:unsupported_value"]
    candidate.evidence["/name"].quote = "unobserved quote"
    assert verifier.verify(candidate, page, schema, task) == ["/name:quote_not_observed"]
