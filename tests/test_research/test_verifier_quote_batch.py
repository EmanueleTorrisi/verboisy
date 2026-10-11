# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Native dispatch preserves scope gates, ordered errors and value authorization."""

import json

import pytest
from verboisy.evidence import verify as verifier
from verboisy.evidence.models import Candidate, FieldRule, Proof, Snapshot, Source, TaskSpec
from verboisy.evidence.quote_match import regex_quote_observed

from benchmarks.workloads import SCHEMA, evidence, records


def matching_batch(cases, *, backend):
    assert backend == "native"
    return [regex_quote_observed(*case) for case in cases]


def mixed_errors():
    page, candidate = evidence(records(1)[0], 0)
    candidate.record["name"] = "Different"
    candidate.evidence["/amount"].quote = "97"
    candidate.evidence["/group"].source = "absent"
    candidate.evidence.pop("/note")
    candidate.evidence["/unknown"] = Proof(source="name", quote="unobserved")
    task = TaskSpec(identity_fields=["/absent_identity"])
    return page, candidate, task


def test_mixed_error_order_and_scalar_rollback(monkeypatch):
    page, candidate, task = mixed_errors()
    expected = [
        "unknown_evidence_pointer",
        "/name:unsupported_value",
        "/amount:quote_not_observed",
        "/group:source_outside_entity",
        "/note:missing_evidence",
        "/absent_identity:invalid_identity",
    ]
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "python")
    assert verifier.verify(candidate, page, SCHEMA, task) == expected
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", matching_batch)
    assert verifier.verify(candidate, page, SCHEMA, task) == expected
    monkeypatch.setattr(
        verifier,
        "quote_observed",
        lambda *case, backend: matching_batch([case], backend=backend)[0],
    )
    assert verifier.verify(candidate, page, SCHEMA, task, batch_quotes=False) == expected


def test_only_eligible_proofs_enter_the_batch(monkeypatch):
    page = Snapshot(
        id="fixture",
        url="https://example.invalid/data",
        fetched_at="2026-10-08T00:00:00Z",
        content_hash="hash",
        truncated=False,
        sources=[
            Source(id="text", kind="text", text="cat", scope="s"),
            Source(id="link", kind="link", text="link", href="https://other.invalid/", scope="s"),
            Source(id="outside", kind="text", text="outside", scope="other"),
        ],
    )
    candidate = Candidate(
        scope="s",
        record={
            "name": "cat",
            "url": page.url,
            "link": "https://other.invalid/",
            "dataset": "cat",
            "null": None,
            "outside": "outside",
        },
        evidence={
            "/name": Proof(source="text", quote="cat"),
            "/url": Proof(source="page", quote="", transform="page_url"),
            "/link": Proof(source="link", quote="", transform="href"),
            "/dataset": Proof(source="text", quote="cat", transform="dataset"),
            "/outside": Proof(source="outside", quote="outside"),
        },
    )
    calls = []

    def capture(cases, *, backend):
        calls.append(cases)
        return matching_batch(cases, backend=backend)

    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", capture)
    task = TaskSpec(field_rules={"/url": FieldRule(source="page_url")})
    assert verifier.verify(candidate, page, {"type": "object"}, task) == [
        "/dataset:dataset_proof_not_grounded",
        "/outside:source_outside_entity",
    ]
    assert calls == [[("cat", "cat", False)]]


def test_more_than_one_native_chunk_preserves_all_fields(monkeypatch):
    page, candidate = evidence(records(1)[0], 0)
    candidate.record = {f"field{i}": "cat" for i in range(4097)}
    candidate.evidence = {
        "/" + name: Proof(source="name", quote="cat") for name in candidate.record
    }
    page.sources[0].text = "cat"
    calls = []

    def capture(cases, *, backend):
        calls.append(len(cases))
        return matching_batch(cases, backend=backend)

    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", capture)
    assert verifier.verify(candidate, page, {"type": "object"}, TaskSpec()) == []
    assert calls == [4096, 1]


@pytest.mark.parametrize("value", ["normalized", 42, True, None])
def test_batch_mapping_authorization_remains_json_based(monkeypatch, value):
    page, candidate = evidence(records(1)[0], 0)
    candidate.record["name"] = value
    rule = FieldRule(
        mapping={json.dumps(value, ensure_ascii=False): candidate.evidence["/name"].quote}
    )
    task = TaskSpec(allow_nulls=False, field_rules={"/name": rule})
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", matching_batch)
    assert verifier.verify(candidate, page, {"type": "object"}, task) == []
    rule.mapping[json.dumps(value, ensure_ascii=False)] = "different source value"
    assert verifier.verify(candidate, page, {"type": "object"}, task) == ["/name:unsupported_value"]


def test_batch_failure_cannot_return_partial_verification(monkeypatch):
    page, candidate, task = mixed_errors()

    def failed(cases, *, backend):
        raise RuntimeError("batch failed")

    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", failed)
    with pytest.raises(RuntimeError, match="batch failed"):
        verifier.verify(candidate, page, SCHEMA, task)


def test_python_and_non_text_proofs_do_not_load_native(monkeypatch):
    page, candidate = evidence(records(1)[0], 0)

    def forbidden(cases, *, backend):
        pytest.fail("Native batch should not be invoked")

    monkeypatch.setattr(verifier, "quotes_observed", forbidden)
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "python")
    assert verifier.verify(candidate, page, SCHEMA, TaskSpec()) == []
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    candidate.scope = "outside"
    assert verifier.verify(candidate, page, SCHEMA, TaskSpec()) == [
        "/name:source_outside_entity",
        "/amount:source_outside_entity",
        "/group:source_outside_entity",
        "/note:source_outside_entity",
    ]


def test_error_order_handles_colons_in_field_names(monkeypatch):
    page, candidate = evidence(records(1)[0], 0)
    candidate.record = {"a:part": "different", "b": "missing"}
    candidate.evidence = {
        "/a:part": Proof(source="name", quote=page.sources[0].text),
        "/b": Proof(source="absent", quote="missing"),
    }
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "native")
    monkeypatch.setattr(verifier, "quotes_observed", matching_batch)
    assert verifier.verify(candidate, page, {"type": "object"}, TaskSpec()) == [
        "/a:part:unsupported_value",
        "/b:source_outside_entity",
    ]
