# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal metadata declarations are bounded, strict, and replayable."""

import hashlib
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from verboisy.evidence import html_metadata
from verboisy.evidence.html_metadata import HtmlMetadataError, HtmlMetadataSpec, literal_metadata
from verboisy.evidence.html_metadata_snapshot import html_metadata_candidate, html_metadata_snapshot
from verboisy.evidence.models import Source, TaskSpec

PLAN = HtmlMetadataSpec.model_validate(
    {
        "region": "main#details",
        "fields": {
            "heading": {"selector": "h1.title"},
            "issued": {"selector": "dl.metadata", "label": "Issued:"},
            "edition": {"selector": "dl.metadata", "label": "Edition", "on_missing": "null"},
        },
    }
)
PRIMARY = (
    '<html><head><title>Ignored</title></head><body><main id="details">'
    '<h1 class="title">Pump &amp; Valve <em>Reference</em></h1>'
    '<h1 class="title" hidden>Hidden alternative</h1>'
    '<dl class="metadata"><dt>Issued:</dt><dd><span>11 Nov 2026</span></dd>'
    "<dt>Region</dt><dd>North</dd></dl><p>Edition 15 is available elsewhere.</p>"
    '</main><dl class="metadata"><dt>Edition</dt><dd>Wrong region</dd></dl></body></html>'
)
EXPECTED = {"heading": "Pump & Valve Reference", "issued": "11 Nov 2026", "edition": None}


class LiteralMetadataTests(unittest.TestCase):
    def test_copies_visible_text_and_limits_absence_to_the_declared_list(self) -> None:
        self.assertEqual(literal_metadata(PRIMARY, PLAN), EXPECTED)
        split = PRIMARY.replace("Pump", "<span>Pu</span><span>mp</span>")
        self.assertEqual(literal_metadata(split, PLAN), EXPECTED)
        grouped = PRIMARY.replace(
            "<dt>Issued:</dt><dd><span>11 Nov 2026</span></dd>" "<dt>Region</dt><dd>North</dd>",
            "<div><dt>Issued</dt><dd>11 Nov 2026</dd></div>"
            "<div><dt>Edition:</dt><dd>007</dd></div>",
        )
        self.assertEqual(literal_metadata(grouped, PLAN), {**EXPECTED, "edition": "007"})

    def test_ambiguous_or_malformed_markup_does_not_become_null(self) -> None:
        cases = (
            (PRIMARY.replace('<main id="details">', "<main>"), "record_region_not_unique"),
            (
                PRIMARY.replace("</main>", '</main><main id="details"></main>'),
                "record_region_not_unique",
            ),
            (
                PRIMARY.replace("</h1>", '</h1><h1 class="title">extra</h1>', 1),
                "field_region_not_unique",
            ),
            (PRIMARY.replace('class="metadata"', 'class="other"', 1), "field_region_not_unique"),
            (
                PRIMARY.replace("<dt>Region</dt><dd>North</dd>", "<dt>Issued</dt><dd>Other</dd>"),
                "ambiguous_definition_label",
            ),
            (PRIMARY.replace("<dd>North</dd>", ""), "malformed_definition_list"),
            (PRIMARY.replace("<dt>Region</dt>", "unwrapped"), "malformed_definition_list"),
            (PRIMARY.replace("<dt>Region</dt>", "<dd>Region</dd>"), "malformed_definition_list"),
            (PRIMARY.replace("<dd>North</dd>", "<dd> </dd>"), "blank_or_oversized_value"),
            (PRIMARY.replace("<dt>Issued:</dt>", "<dt>Unknown</dt>"), "required_field_missing"),
            (PRIMARY.replace("</main>", ""), "unbalanced_layout"),
            (PRIMARY + "<section>", "unbalanced_layout"),
            (
                PRIMARY.replace('<main id="details">', '<main id="details" id="other">'),
                "ambiguous_attributes",
            ),
        )
        for html, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(HtmlMetadataError, reason):
                literal_metadata(html, PLAN)

    def test_capture_and_binding_limits(self) -> None:
        for key in ("MAX_HTML_CHARS", "MAX_NODES", "MAX_DEPTH", "MAX_TEXT_CHARS"):
            with (
                self.subTest(limit=key),
                patch.object(html_metadata, key, 2),
                self.assertRaises(HtmlMetadataError),
            ):
                literal_metadata(PRIMARY, PLAN)
        with self.assertRaisesRegex(HtmlMetadataError, "metadata_evidence_limit"):
            html_metadata_snapshot(PRIMARY, "https://docs.example.test/pump", 20, PLAN)

    def test_binding_order_does_not_change_proofs_and_null_has_no_proof(self) -> None:
        url = "https://docs.example.test/pump"
        snap = html_metadata_snapshot(PRIMARY, url, 4096, PLAN)
        self.assertEqual(snap.content_hash, hashlib.sha256(PRIMARY.encode()).hexdigest())
        candidate = html_metadata_candidate(snap, PLAN)
        self.assertEqual(candidate.record, EXPECTED)
        self.assertEqual(set(candidate.evidence), {"/heading", "/issued"})
        self.assertEqual(candidate.evidence["/heading"].quote, EXPECTED["heading"])
        reordered = PLAN.model_copy(update={"fields": dict(reversed(tuple(PLAN.fields.items())))})
        self.assertEqual(html_metadata_candidate(snap, reordered), candidate)

    def test_inconsistent_saved_sources_refuse_replay(self) -> None:
        snap = html_metadata_snapshot(PRIMARY, "https://docs.example.test/pump", 4096, PLAN)
        bogus = Source(id="unexpected", scope="html-metadata", kind="text", text="other")
        for changes in (
            {"truncated": True},
            {"dataset_asset_id": "unrelated"},
            {"sources": [bogus]},
            {"sources": [snap.sources[0], snap.sources[0]]},
            {"sources": []},
            {"sources": [snap.sources[0].model_copy(update={"scope": "other"}), *snap.sources[1:]]},
            {
                "sources": [
                    snap.sources[0].model_copy(update={"text": "  damaged"}),
                    *snap.sources[1:],
                ]
            },
            {
                "sources": [
                    snap.sources[0],
                    snap.sources[1].model_copy(update={"text": ""}),
                    snap.sources[2],
                ]
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(HtmlMetadataError):
                html_metadata_candidate(snap.model_copy(update=changes), PLAN)

    def test_strict_declarations_and_existing_saved_task_shape(self) -> None:
        self.assertNotIn("html_metadata", TaskSpec().model_dump())
        self.assertNotIn('"html_metadata"', TaskSpec().model_dump_json())
        task = TaskSpec(html_metadata=PLAN)
        self.assertEqual(TaskSpec.model_validate_json(task.model_dump_json()), task)
        for change in (
            {"region": "main > h1"},
            {"fields": {"id": {"selector": "h1"}}},
            {"fields": {"heading": {"selector": "h1", "label": "X"}}},
            {"fields": {"heading": {"selector": "dl", "label": ":"}}},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                HtmlMetadataSpec.model_validate({**PLAN.model_dump(), **change})
        for change in (
            {"column_tables": [{"table": 1}]},
            {"field_rules": {"/heading": {}}},
            {"dataset_sources": [{"url": "https://docs.example.test/pump", "format": "csv"}]},
            {"pagination_selector": "a.next"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                TaskSpec.model_validate({**task.model_dump(), **change})
