# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Reported live rejection patterns remain rejected; grounded nullable rows can pass."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.evidence.models import Candidate, Snapshot, Source, TaskSpec
from verboisy.extractor.evidenced import EvidenceExtractor

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name_breed": {"type": ["string", "null"]},
            "country_banned": {"type": ["string", "null"]},
            "weight_male": {"type": ["number", "null"]},
            "weight_female": {"type": ["number", "null"]},
        },
        "required": ["name_breed", "country_banned", "weight_male", "weight_female"],
    },
}


def page(text, source_id="e1", scope="s1"):
    return Snapshot(
        id="snapshot",
        url="https://example.test",
        fetched_at="2026-01-01",
        content_hash="fixture",
        truncated=False,
        sources=[Source(id=source_id, kind="text", text=text, scope=scope)],
    )


def candidate(value, proof, pointer="/country_banned"):
    record = {
        "name_breed": None,
        "country_banned": None,
        "weight_male": None,
        "weight_female": None,
    }
    record[pointer[1:]] = value
    return Candidate(scope="s1", record=record, evidence={pointer: proof})


@pytest.mark.parametrize(
    "observation,value,proof,pointer,reason",
    [
        (
            "the Chinese city of Chengdu banned it in 2018",
            "Chengdu, China",
            {
                "source": "e1",
                "quote": "the Chinese city of Chengdu banned it in 2018",
                "transform": "text",
            },
            "/country_banned",
            "unsupported_value",
        ),
        (
            "Ireland",
            "Ireland",
            {"source": "page", "quote": "Ireland", "transform": "text"},
            "/country_banned",
            "source_outside_entity",
        ),
        (
            "Government of Bermuda.",
            "Cane Corso",
            {"source": "e1", "quote": "Cane Corso", "transform": "text"},
            "/name_breed",
            "quote_not_observed",
        ),
        (
            "100",
            100,
            {"source": "e1", "quote": "100", "transform": "text"},
            "/weight_male",
            "unsupported_value",
        ),
    ],
)
async def test_invalid_bindings_rejected_before_review(observation, value, proof, pointer, reason):
    client = SimpleNamespace(complete_json=AsyncMock())
    extractor = EvidenceExtractor(client, SCHEMA, TaskSpec(), "Find banned breeds")
    errors = await extractor.check(candidate(value, proof, pointer), page(observation))
    assert pointer + ":" + reason in errors
    client.complete_json.assert_not_awaited()


async def test_required_nullable_unknowns_allow_grounded_review():
    client = SimpleNamespace(complete_json=AsyncMock())
    client.complete_json.return_value = {
        "relevant": True,
        "same_entity": True,
        "supported_fields": ["/name_breed", "/country_banned"],
        "rejected_fields": [],
    }
    record = Candidate(
        scope="s1",
        record={
            "name_breed": "Example Breed",
            "country_banned": "Country A",
            "weight_male": None,
            "weight_female": None,
        },
        evidence={
            "/name_breed": {"source": "e1", "quote": "Example Breed", "transform": "text"},
            "/country_banned": {"source": "e1", "quote": "Country A", "transform": "text"},
        },
    )
    extractor = EvidenceExtractor(client, SCHEMA, TaskSpec(), "Find banned breeds")
    assert await extractor.check(record, page("Example Breed is banned in Country A.")) == []
    client.complete_json.assert_awaited_once()


async def test_literal_restriction_text_still_requires_semantic_review():
    client = SimpleNamespace(complete_json=AsyncMock())
    client.complete_json.return_value = {
        "relevant": False,
        "same_entity": True,
        "supported_fields": [],
        "rejected_fields": ["/country_banned"],
    }
    record = candidate("Country A", {"source": "e1", "quote": "Country A", "transform": "text"})
    extractor = EvidenceExtractor(client, SCHEMA, TaskSpec(), "Find banned breeds")
    assert await extractor.check(record, page("Ownership conditions apply in Country A.")) == [
        "semantic_review_rejected"
    ]
