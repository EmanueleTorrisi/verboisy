# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Offline regression for the NASA pilot's saved semantic policy, not a live score."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import Candidate, TaskSpec
from verboisy.evidence.snapshot import snapshot
from verboisy.evidence.verify import verify
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings

FIELDS = ("body", "diameter_km", "gravity_m_s2", "number_of_moons")
EXPECTED = [
    {"body": "MERCURY", "diameter_km": 4879, "gravity_m_s2": 3.7, "number_of_moons": 0},
    {"body": "VENUS", "diameter_km": 12104, "gravity_m_s2": 8.9, "number_of_moons": 0},
    {"body": "EARTH", "diameter_km": 12756, "gravity_m_s2": 9.8, "number_of_moons": 1},
]


async def test_saved_nasa_policy_preserves_values_and_pauses_without_more_extraction(tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures/pages/nasa_planetary_factsheet.html"
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "42bdc3f1dae470b85580c6ac66c353964a05d544ad2ac970a6b7d908337a6c3c"
    )
    html = raw.decode("utf-8")
    url = "https://example.test/nasa/"
    task = TaskSpec(
        target_records=3,
        identity_fields=["/body"],
        settle_ms=0,
        allowed_hosts=["example.test"],
        include_paths=["/nasa/"],
        column_tables=[{"table": 1}],
    )
    schema = {
        "type": "array",
        "minItems": 3,
        "maxItems": 3,
        "items": {
            "type": "object",
            "required": list(FIELDS),
            "additionalProperties": False,
            "properties": {
                key: {"type": kind}
                for key, kind in zip(
                    FIELDS, ("string", "integer", "number", "integer"), strict=True
                )
            },
        },
    }
    page = SimpleNamespace(
        evaluate=AsyncMock(
            return_value={
                "url": url,
                "html": html,
                "visible_html": html,
                "oversized": False,
            }
        )
    )
    config = Settings(
        _env_file=None,
        search_provider="disabled",
        action_delay_seconds=0,
        litellm_model="openai/test",
        litellm_api_key="fixture",
        max_dom_chars=12000,
    )
    roles = []

    async def response(_system, prompt):
        payload = json.loads(prompt)
        if "fields" in payload:
            roles.append("semantic_plan")
            # Same sensitivity flags as the failed live pilot. The preceding
            # preflight used all-false flags and could not expose this failure.
            return {
                "fields": [
                    {
                        "pointer": "/" + field,
                        "temporal_class": "slow_changing"
                        if field == "number_of_moons"
                        else "static",
                        "reference_period": "none",
                        "temporal_intent": None,
                        "comparable_across_rows": True,
                        "definition_sensitive": field != "body",
                        "unit_sensitive": field in {"diameter_km", "gravity_m_s2"},
                        "methodology_sensitive": field == "gravity_m_s2",
                        "confidence": 0.9,
                    }
                    for field in FIELDS
                ]
            }
        if "candidate" in payload:
            roles.append("review")
            return {
                "relevant": True,
                "same_entity": True,
                "supported_fields": list(payload["candidate"]["evidence"]),
                "rejected_fields": [],
            }
        if "candidates" in payload:
            roles.append("assessment")
            for candidate in payload["candidates"]:
                assert candidate["required_comparability"] == {
                    "/diameter_km": ["unit", "definition"],
                    "/gravity_m_s2": ["unit", "definition", "methodology_identity"],
                    "/number_of_moons": ["definition"],
                }
            return {
                "candidates": [
                    {"candidate_index": candidate["candidate_index"], "assessments": []}
                    for candidate in payload["candidates"]
                ]
            }
        roles.append("extraction")
        assert roles.count("extraction") <= 2, "Unrelated extraction after target reached"
        sources = {source["id"]: source for source in payload["sources"]}
        candidates = []
        for column in (2, 3, 4):
            ids = [f"table1.row{row}.column{column}.value" for row in (1, 3, 5, 19)]
            if not all(name in sources for name in ids):
                continue
            values = [sources[name]["text"] for name in ids]
            candidates.append(
                {
                    "scope": f"table1.column{column}",
                    "record": dict(
                        zip(
                            FIELDS,
                            (
                                values[0],
                                int(values[1].replace(",", "")),
                                float(values[2]),
                                int(values[3]),
                            ),
                            strict=True,
                        )
                    ),
                    "evidence": {
                        "/" + field: {
                            "source": name,
                            "quote": sources[name]["text"],
                            "transform": kind,
                        }
                        for field, name, kind in zip(
                            FIELDS, ids, ("text", "integer", "number", "integer"), strict=True
                        )
                    },
                }
            )
        return {"candidates": candidates}

    store = ResearchStore(str(tmp_path / "nasa.db"))
    try:
        rid = store.create(
            "Extract the three specified bodies and preserve source values", schema, task, None
        )
        store.queue(rid, url, 0, None)
        runner = ResearchRunner(store, rid, config)
        runner.browser = SimpleNamespace(
            start=AsyncMock(),
            close=AsyncMock(),
            get_page=AsyncMock(return_value=page),
            navigate_to=AsyncMock(),
        )
        runner.client.complete_json = AsyncMock(side_effect=response)
        assert await runner.run(1) == ("PAUSED", "dataset_consistency_gaps")
        assert [
            {k: v for k, v in row.items() if k != "id"} for row in store.records(rid)
        ] == EXPECTED
        assert runner.dataset_consistency_gaps() == (
            "/diameter_km:unknown_definition",
            "/diameter_km:unknown_unit",
            "/gravity_m_s2:unknown_definition",
            "/gravity_m_s2:unknown_methodology",
            "/gravity_m_s2:unknown_unit",
            "/number_of_moons:unknown_definition",
        )
        assert roles == [
            "semantic_plan",
            "extraction",
            "review",
            "review",
            "assessment",
            "extraction",
            "review",
            "assessment",
        ]
        reconstructed = snapshot(html, url, column_tables=task.column_tables)
        for entry in store.evidence(rid):
            assert (
                verify(
                    Candidate.model_validate(entry["candidate"]),
                    reconstructed,
                    schema["items"],
                    task,
                )
                == []
            )
        assert store.load(rid)["status"] == "PAUSED"
        assert len(store.events(rid, "dataset_consistency_gap")) == 1
    finally:
        store.close()
