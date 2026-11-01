# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit source and comparison contracts survive model suggestions and journaling."""

from dataclasses import replace
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock

from verboisy.core.fitness import (
    FieldSemantics,
    dataset_definition_consistency_errors,
    dataset_methodology_consistency_errors,
    dataset_unit_consistency_errors,
)
from verboisy.core.planner import TemporalIntent
from verboisy.core.semantic_plan_journal import journal_field_semantics
from verboisy.core.semantic_planner import (
    _FieldProposal,
    _merge,
    _validate_semantic_response_contract,
    semantic_plan_event,
)
from verboisy.utils.exceptions import LLMResponseError


def model_proposal(**updates):
    return _FieldProposal.model_validate(
        {
            "pointer": "/measurement",
            "temporal_class": "static",
            "reference_period": "none",
            "temporal_intent": None,
            "definition_sensitive": True,
            "unit_sensitive": True,
            "methodology_sensitive": True,
            "comparable_across_rows": True,
            "confidence": 0.9,
            **updates,
        }
    )


def source_policy():
    return FieldSemantics(pointer="/measurement", basis="explicit", confidence=1.0)


def comparison_policy():
    return replace(
        source_policy(),
        definition_sensitive=True,
        unit_sensitive=True,
        methodology_sensitive=True,
        comparable_across_rows=True,
    )


class ExplicitComparisonContractTests(TestCase):
    def test_model_cannot_add_comparison_to_explicit_source_values(self):
        result = _merge(source_policy(), model_proposal())
        self.assertEqual(result, source_policy())
        self.assertEqual(result.basis, "explicit")

    def test_model_cannot_remove_explicit_comparison_requirements(self):
        result = _merge(
            comparison_policy(),
            model_proposal(
                definition_sensitive=False,
                unit_sensitive=False,
                methodology_sensitive=False,
                comparable_across_rows=False,
            ),
        )
        self.assertEqual(result, comparison_policy())

    def test_undeclared_fields_still_follow_inferred_comparison_requirements(self):
        result = _merge(FieldSemantics(pointer="/measurement"), model_proposal())
        self.assertEqual(result.basis, "model")
        self.assertTrue(result.comparable_across_rows)
        self.assertTrue(result.methodology_sensitive)

    def test_mixed_response_preserves_explicit_fields_without_relaxing_other_fields(self):
        declared = source_policy()
        inferred = FieldSemantics(pointer="/other")
        result = _validate_semantic_response_contract(
            {
                "fields": [
                    model_proposal().model_dump(),
                    model_proposal(pointer="/other").model_dump(),
                ]
            },
            baseline={declared.pointer: declared, inferred.pointer: inferred},
            field_schemas={"/measurement": {"type": "number"}, "/other": {"type": "number"}},
        )
        self.assertEqual(result["/measurement"], declared)
        self.assertTrue(result["/other"].comparable_across_rows)
        self.assertEqual(result["/other"].basis, "model")

    def test_explicit_fields_do_not_make_incomplete_model_responses_acceptable(self):
        for fields in ([], [model_proposal().model_dump()] * 2):
            with self.subTest(fields=fields), self.assertRaises(LLMResponseError):
                _validate_semantic_response_contract(
                    {"fields": fields},
                    baseline={"/measurement": source_policy()},
                    field_schemas={"/measurement": {"type": "number"}},
                )

    def test_explicit_required_temporal_evidence_cannot_be_removed(self):
        field = replace(
            comparison_policy(), temporal_class="time_series", reference_period="required"
        )
        with self.assertRaises(ValueError):
            _merge(field, model_proposal())
        result = _merge(
            field,
            model_proposal(temporal_intent={"mode": "year", "start_year": 2020, "end_year": 2020}),
        )
        self.assertEqual(result.reference_period, "required")
        self.assertEqual(result.temporal_intent, TemporalIntent("year", 2020, 2020))

    def test_missing_comparison_evidence_is_still_a_blocker_when_required(self):
        observation = ({"pointer": "/measurement", "record_id": "fixture"},)
        declared = {"/measurement": comparison_policy()}
        self.assertEqual(
            dataset_definition_consistency_errors(observation, declared),
            ("/measurement:unknown_definition",),
        )
        self.assertEqual(
            dataset_methodology_consistency_errors(observation, declared),
            ("/measurement:unknown_methodology",),
        )
        self.assertEqual(
            dataset_unit_consistency_errors(observation, declared),
            ("/measurement:unknown_unit",),
        )

    def test_explicit_source_values_do_not_claim_cross_row_comparability(self):
        observation = ({"pointer": "/measurement", "record_id": "fixture"},)
        declared = {"/measurement": source_policy()}
        for check in (
            dataset_definition_consistency_errors,
            dataset_methodology_consistency_errors,
            dataset_unit_consistency_errors,
        ):
            self.assertEqual(check(observation, declared), ())
        event = semantic_plan_event(
            declared, research_year=2026, temporal_intent=TemporalIntent("latest")
        )
        self.assertFalse(event["fields"][0]["comparable_across_rows"])
        self.assertEqual(event["fields"][0]["basis"], "explicit")


class ExplicitComparisonJournalTests(IsolatedAsyncioTestCase):
    def runner(self, field):
        return SimpleNamespace(
            semantic_plan_ready=False,
            field_semantics={field.pointer: field},
            temporal_intent=TemporalIntent("latest"),
            current_year=2026,
            store=SimpleNamespace(event=Mock()),
            rid="fixture",
            extractor=SimpleNamespace(),
            semantic_planning_available=Mock(return_value=True),
            client=object(),
            goal="Preserve supplied values.",
            schema={"type": "array"},
        )

    async def test_fully_explicit_contract_is_journaled_without_a_model_call(self):
        for field in (source_policy(), comparison_policy()):
            with self.subTest(comparable=field.comparable_across_rows):
                runner = self.runner(field)
                classify = AsyncMock(side_effect=AssertionError("No model call expected"))
                await journal_field_semantics(runner, classify, semantic_plan_event)
                classify.assert_not_awaited()
                runner.semantic_planning_available.assert_not_called()
                runner.store.event.assert_called_once()
                self.assertTrue(runner.semantic_plan_ready)
                self.assertEqual(runner.extractor.field_semantics, runner.field_semantics)
                payload = runner.store.event.call_args.args[2]
                self.assertEqual(
                    payload["fields"][0]["comparable_across_rows"],
                    field.comparable_across_rows,
                )
                await journal_field_semantics(runner, classify, semantic_plan_event)
                runner.store.event.assert_called_once()

    async def test_journal_failure_does_not_publish_readiness_or_extractor_state(self):
        runner = self.runner(source_policy())
        runner.store.event.side_effect = OSError("fixture disk failure")
        classify = AsyncMock(side_effect=AssertionError("No model call expected"))
        with self.assertRaises(OSError):
            await journal_field_semantics(runner, classify, semantic_plan_event)
        self.assertFalse(runner.semantic_plan_ready)
        self.assertFalse(hasattr(runner.extractor, "field_semantics"))
        classify.assert_not_awaited()

    async def test_inferred_contract_still_uses_the_semantic_planner(self):
        runner = self.runner(FieldSemantics(pointer="/measurement"))
        classified = {"/measurement": replace(comparison_policy(), basis="model")}
        classify = AsyncMock(return_value=classified)
        await journal_field_semantics(runner, classify, semantic_plan_event)
        classify.assert_awaited_once()
        self.assertEqual(runner.extractor.field_semantics, classified)
        self.assertTrue(runner.semantic_plan_ready)
