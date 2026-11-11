# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Review observed claims without treating permitted nulls as asserted facts."""

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from verboisy.core.proposal_review import review_page_proposal
from verboisy.evidence.models import (
    Candidate,
    FieldRule,
    PageProposal,
    Proof,
    Snapshot,
    Source,
    TaskSpec,
)
from verboisy.evidence.verify import leaves
from verboisy.extractor.evidenced import EvidenceExtractor
from verboisy.extractor.proof_preparation import prepare_candidate_proofs

MISSING = "/measurements/0"
ZERO = "/measurements/1"
NAME = "/item~1name"
FLAG = "/active"
FACTS = [NAME, ZERO, FLAG]
SCHEMA = {
    "type": "object",
    "properties": {
        "item/name": {"type": "string"},
        "measurements": {"type": "array", "items": {"type": ["null", "integer"]}},
        "active": {"type": "boolean"},
        "optional_note": {"type": "string"},
    },
    "required": ["item/name", "measurements", "active"],
    "additionalProperties": False,
}


def fixture():
    candidate = Candidate.model_validate(
        {
            "scope": "s1",
            "record": {"item/name": "Pump A", "measurements": [None, 0], "active": False},
            "evidence": {
                NAME: {"source": "e1", "quote": "Pump A", "transform": "text"},
                MISSING: {"source": "e2", "quote": "not measured", "transform": "text"},
                ZERO: {"source": "e3", "quote": "0", "transform": "integer"},
                FLAG: {"source": "e4", "quote": "false", "transform": "boolean"},
            },
            "temporal_evidence": {
                MISSING: {"source": "e5", "quote": "2021", "reference_year": 2021},
                ZERO: {"source": "e6", "quote": "2024", "reference_year": 2024},
            },
        }
    )
    page = Snapshot(
        id="snapshot",
        url="https://example.test/pump-a",
        fetched_at="2026-11-11T00:00:00Z",
        content_hash="capture",
        sources=[
            Source(id="e1", kind="text", text="Pump A", scope="s1"),
            Source(id="e2", kind="text", text="not measured", scope="s1"),
            Source(id="e3", kind="text", text="0", scope="s1"),
            Source(id="e4", kind="text", text="false", scope="s1"),
            Source(id="e5", kind="text", text="2021", scope="page"),
            Source(id="e6", kind="text", text="2024", scope="page"),
            Source(id="e7", kind="text", text="Pump A", scope="s2"),
        ],
        truncated=False,
    )
    return candidate, page


class ReviewTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.candidate, self.page = fixture()
        self.task = TaskSpec(allow_nulls=True, identity_fields=[NAME])
        self.reply = {
            "relevant": True,
            "same_entity": True,
            "supported_fields": FACTS.copy(),
            "rejected_fields": [],
        }
        self.review = AsyncMock(return_value=self.reply)
        self.extractor = EvidenceExtractor(
            SimpleNamespace(complete_json=self.review),
            SCHEMA,
            self.task,
            "Read the pump inventory and leave unobserved measurements null.",
        )

    async def test_review_ignores_one_vote_on_an_allowed_null(self):
        before = self.candidate.model_dump()
        for key in ("supported_fields", "rejected_fields"):
            with self.subTest(vote_list=key):
                self.review.return_value = {**self.reply, key: [*self.reply[key], MISSING]}
                self.assertEqual(await self.extractor.check(self.candidate, self.page), [])
                body = json.loads(self.review.await_args.args[1])
                self.assertEqual(body["candidate"]["record"], before["record"])
                self.assertEqual(body["review_pointers"], FACTS)
                self.assertEqual(set(body["candidate"]["evidence"]), set(FACTS))
                self.assertEqual(set(body["candidate"]["temporal_evidence"]), {ZERO})
                self.assertEqual([source["id"] for source in body["temporal_context"]], ["e6"])
                self.assertEqual(self.candidate.model_dump(), before)

    async def test_incomplete_unsupported_or_ambiguous_reviews_fail_closed(self):
        for override in (
            {"relevant": False},
            {"same_entity": False},
            {"supported_fields": [NAME, ZERO]},
            {"supported_fields": [NAME, ZERO], "rejected_fields": [FLAG]},
            {"supported_fields": [*FACTS, "/optional_note"]},
            {"rejected_fields": ["/invented"]},
            {"supported_fields": [*FACTS, NAME]},
            {"rejected_fields": [MISSING, MISSING]},
            {"supported_fields": [*FACTS, MISSING], "rejected_fields": [MISSING]},
            {"supported_fields": [*FACTS, MISSING, MISSING]},
        ):
            with self.subTest(override=override):
                self.review.return_value = {**self.reply, **override}
                self.assertEqual(
                    await self.extractor.check(self.candidate, self.page),
                    ["semantic_review_rejected"],
                )

    async def test_literal_scope_validation_still_precedes_review(self):
        self.candidate.evidence[NAME] = Proof(source="e7", quote="Pump A", transform="text")
        self.assertEqual(
            await self.extractor.check(self.candidate, self.page),
            [f"{NAME}:source_outside_entity"],
        )
        self.review.assert_not_awaited()

    async def test_null_policy_remains_enforced_before_review(self):
        self.task.allow_nulls = False
        self.candidate.evidence.pop(MISSING)
        self.assertEqual(
            await self.extractor.check(self.candidate, self.page),
            [f"{MISSING}:missing_evidence"],
        )
        self.review.assert_not_awaited()

    async def test_required_property_must_still_exist(self):
        self.candidate.record.pop("measurements")
        self.assertEqual(await self.extractor.check(self.candidate, self.page), ["schema_invalid"])
        self.review.assert_not_awaited()

    async def test_nonnullable_task_still_reviews_observed_values(self):
        self.task.allow_nulls = False
        self.candidate.record["measurements"][0] = 9
        self.candidate.evidence[MISSING] = Proof(source="e2", quote="9", transform="integer")
        next(source for source in self.page.sources if source.id == "e2").text = "9"
        self.reply["supported_fields"].append(MISSING)
        self.assertEqual(await self.extractor.check(self.candidate, self.page), [])

    async def handoff(self):
        runner = SimpleNamespace(
            rid="run",
            extractor=self.extractor,
            store=SimpleNamespace(event=Mock()),
            source_assess_candidates=AsyncMock(),
        )
        proposal = PageProposal(candidates=[self.candidate])
        [outcome] = await review_page_proposal(
            runner,
            self.page,
            self.page,
            proposal,
            lambda *_args: None,
            lambda _proposal: [],
            lambda *_args: None,
        )
        return runner, outcome

    async def test_proposal_handoff_drops_null_proofs_without_changing_values(self):
        self.reply["rejected_fields"] = [MISSING]
        runner, (reviewed, errors) = await self.handoff()
        self.assertEqual(errors, [])
        self.assertEqual(reviewed.record, self.candidate.record)
        self.assertEqual(set(reviewed.evidence), set(FACTS))
        self.assertEqual(set(reviewed.temporal_evidence), {ZERO})
        self.assertIn(MISSING, self.candidate.evidence)
        self.assertIn(MISSING, self.candidate.temporal_evidence)
        self.assertEqual(
            [call.args[1] for call in runner.store.event.call_args_list],
            ["extraction_proposal", "unasserted_proofs_discarded"],
        )
        original = runner.store.event.call_args_list[0].args[2]["proposal"]["candidates"][0]
        self.assertEqual(original, self.candidate.model_dump(mode="json"))
        self.assertEqual(
            runner.store.event.call_args.args[2],
            {
                "snapshot_id": self.page.id,
                "candidate_index": 0,
                "value_proofs": [MISSING],
                "temporal_proofs": [MISSING],
            },
        )
        runner.source_assess_candidates.assert_awaited_once_with(self.page, [reviewed])

    def test_proof_preparation_leaves_null_proposals_intact(self):
        before = self.candidate.model_dump()
        kept, changes = prepare_candidate_proofs(self.candidate, self.page, self.task, {})
        self.assertIs(kept, self.candidate)
        self.assertEqual(kept.model_dump(), before)
        self.assertEqual(changes, [])

    async def test_rejected_proposal_keeps_unreviewed_proofs_for_diagnosis(self):
        self.reply["same_entity"] = False
        runner, (reviewed, errors) = await self.handoff()
        self.assertEqual(errors, ["semantic_review_rejected"])
        self.assertIs(reviewed, self.candidate)
        self.assertIn(MISSING, reviewed.evidence)
        self.assertEqual(
            [call.args[1] for call in runner.store.event.call_args_list],
            ["extraction_proposal"],
        )
        runner.source_assess_candidates.assert_not_awaited()

    async def test_absent_null_proofs_are_not_created(self):
        self.candidate.evidence.pop(MISSING)
        self.candidate.temporal_evidence.pop(MISSING)
        runner, (reviewed, errors) = await self.handoff()
        self.assertEqual(errors, [])
        self.assertIs(reviewed, self.candidate)
        self.assertEqual(
            [call.args[1] for call in runner.store.event.call_args_list],
            ["extraction_proposal"],
        )

    async def test_explicitly_mapped_null_keeps_its_checked_proof(self):
        self.task.allow_nulls = False
        self.task.field_rules[MISSING] = FieldRule(mapping={"null": "not measured"})
        _, (reviewed, errors) = await self.handoff()
        self.assertEqual(errors, [])
        self.assertIs(reviewed, self.candidate)
        self.assertEqual(reviewed.evidence[MISSING].quote, "not measured")

    async def test_captured_dataset_null_keeps_source_proof(self):
        sources = []
        for pointer, value in leaves(self.candidate.record).items():
            literal = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            sources.append(Source(id=pointer, kind="text", text=literal, scope="s1"))
            self.candidate.evidence[pointer] = Proof(
                source=pointer, quote=literal, transform="dataset"
            )
        self.candidate.temporal_evidence.clear()
        self.page = self.page.model_copy(
            update={"sources": sources, "dataset_asset_id": "capture", "dataset_row_index": 1}
        )
        _, (reviewed, errors) = await self.handoff()
        self.assertEqual(errors, [])
        self.assertIs(reviewed, self.candidate)
        self.assertEqual(reviewed.evidence[MISSING].quote, "null")
