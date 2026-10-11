# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Runner and SQLite refresh integration with scripted proposals and browser pages.

Literal verification runs normally; semantic decisions are controlled test inputs.
"""

from verboisy import arun
from verboisy.evidence.models import Proof, Snapshot, TaskSpec
from verboisy.evidence.verify import verify

from tests.test_research.test_contracts import task


async def test_runner_refreshes_equal_value_and_preserves_evidence(
    config,
    world,
    monkeypatch,
):
    from verboisy.core.fitness import FieldSemantics
    from verboisy.core.planner import TemporalIntent
    from verboisy.core.research import ResearchRunner
    from verboisy.evidence.models import (
        Candidate,
        PageProposal,
        TemporalProof,
    )
    from verboisy.extractor.evidenced import EvidenceExtractor
    from verboisy.storage.research import ResearchStore

    from tests.test_research.test_contracts import PAGES

    for suffix, year in [("a", 2022), ("b", 2025)]:
        monkeypatch.setitem(
            PAGES, f"https://people.test/{suffix}", f"<p>same-id</p><p>100</p><p>{year}</p>"
        )

    schema = {
        "type": "object",
        "properties": {
            "customer": {"type": "string"},
            "population": {"type": "integer"},
        },
        "required": [
            "customer",
            "population",
        ],
        "additionalProperties": False,
    }

    semantics = {
        "/customer": FieldSemantics(
            pointer="/customer",
            temporal_class="static",
            reference_period="none",
            confidence=1.0,
            basis="model",
        ),
        "/population": FieldSemantics(
            pointer="/population",
            temporal_class="mutable",
            reference_period="required",
            temporal_intent=TemporalIntent(mode="latest"),
            comparable_across_rows=True,
            confidence=1.0,
            basis="model",
        ),
    }

    async def ensure_semantics(self):
        self.field_semantics = semantics
        self.semantic_plan_ready = True
        self.extractor.field_semantics = semantics

    async def propose(self, page, sources):
        if page.url.endswith("/a"):
            population = 100
            year = 2022
        else:
            population = 100
            year = 2025

        by_text = {source.text: source for source in sources}
        return PageProposal(
            candidates=[
                Candidate(
                    scope="page",
                    record={
                        "customer": "same-id",
                        "population": population,
                    },
                    evidence={
                        "/customer": Proof(source=by_text["same-id"].id, quote="same-id"),
                        "/population": Proof(
                            source=by_text["100"].id, quote="100", transform="integer"
                        ),
                    },
                    temporal_evidence={
                        "/population": TemporalProof(
                            source=by_text[str(year)].id,
                            quote=str(year),
                            reference_year=year,
                        )
                    },
                )
            ],
            priority_links=[],
        )

    async def check(
        self,
        candidate,
        page,
    ):
        return verify(candidate, page, schema, TaskSpec(identity_fields=["/customer"]))

    monkeypatch.setattr(
        ResearchRunner,
        "ensure_field_semantics",
        ensure_semantics,
    )
    monkeypatch.setattr(
        EvidenceExtractor,
        "propose",
        propose,
    )
    monkeypatch.setattr(
        EvidenceExtractor,
        "check",
        check,
    )

    result = await arun(
        goal="Find latest population",
        schema=schema,
        task=task(
            seed_urls=[
                "https://people.test/a",
                "https://people.test/b",
            ],
            allowed_hosts=["people.test"],
            target_records=2,
            identity_fields=["/customer"],
            max_depth=0,
            max_pages=2,
        ),
        config=config,
    )

    assert [{k: v for k, v in row.items() if k != "id"} for row in result.records] == [
        {
            "customer": "same-id",
            "population": 100,
        }
    ]

    assert result.records[0]["id"] == 1

    store = ResearchStore(config.sqlite_db_path)

    try:
        stored_rows = store.records(result.run_id)
        assert len(stored_rows) == 1
        internal_stable_id = stored_rows[0]["id"]

        assert store.summary(result.run_id)["identity_conflicts"] == 0

        superseded = store.events(
            result.run_id,
            "candidate_superseded",
        )

        assert len(superseded) == 1
        assert superseded[0]["payload"]["stable_id"] == internal_stable_id

        comparisons = store.events(
            result.run_id,
            "candidate_comparison",
        )

        assert any(event["payload"]["preference"] == "new" for event in comparisons)

        evidence = store.evidence(result.run_id)
        assert (
            evidence[0]["candidate"]["temporal_evidence"]["/population"]["reference_year"] == 2025
        )
        assert evidence[0]["snapshot"]["url"] == "https://people.test/b"
        assert all(
            verify(
                Candidate.model_validate(row["candidate"]),
                Snapshot.model_validate(row["snapshot"]),
                schema,
                TaskSpec(identity_fields=["/customer"]),
            )
            == []
            for row in evidence
        )
        old_id = superseded[0]["payload"]["previous_candidate_id"]
        historical = store.db.execute(
            "SELECT payload FROM candidates WHERE id=?", (old_id,)
        ).fetchone()
        assert (
            Candidate.model_validate_json(historical["payload"])
            .temporal_evidence["/population"]
            .reference_year
            == 2022
        )
    finally:
        store.close()
    reopened = ResearchStore(config.sqlite_db_path)
    try:
        assert reopened.evidence(result.run_id) == evidence
        assert reopened.records(result.run_id) == stored_rows
    finally:
        reopened.close()
