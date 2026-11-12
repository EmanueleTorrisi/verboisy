# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal table selection, layout bounds and same-row evidence replay."""

from copy import deepcopy
from unittest import TestCase

from pydantic import ValidationError
from verboisy.evidence.html_table import HtmlTableError, HtmlTableSpec, literal_table_rows
from verboisy.evidence.html_table_snapshot import html_table_candidates, html_table_snapshot
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.verify import verify
from verboisy.research_contract import validate_research_contract
from verboisy.utils.exceptions import VerboisyError

URL = "https://example.test/inventory"
SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "stock": {"type": "integer"},
        "note": {"type": "string"},
    },
    "required": ["code", "stock", "note"],
    "additionalProperties": False,
}
PLAN = {
    "selector": "table#inventory",
    "fields": {
        "code": {"header": "Product code"},
        "stock": {"header": "On hand", "value_type": "integer"},
        "note": {"header": "Note"},
    },
    "key_field": "code",
    "keys": ["007", "002"],
}
HEADER = "<tr><th>Note</th><th> On&nbsp; hand </th><th>Product code</th><th>Unbound</th></tr>"
ROW = '<tr><td>Bench<br>kit</td><td>-12</td><th scope="row">002</th><td>ignore</td></tr>'
OTHER = (
    "<tr><td><span hidden>wrong</span>https://example.test/</td>"
    "<td>0</td><td>007</td><td>unused</td></tr>"
)
SKIP = "<tr><td>Unselected</td><td>1,234</td><td>003-006</td><td></td></tr>"
HIDDEN = "<tr hidden><td>Wrong</td><td>55</td><td>007</td><td></td></tr>"


def page(*rows: str, header: str = HEADER) -> str:
    return (
        '<table id="inventory"><thead>'
        + header
        + "</thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def task(plan: HtmlTableSpec | None = None) -> TaskSpec:
    return TaskSpec(
        html_table=plan or HtmlTableSpec.model_validate(PLAN),
        seed_urls=[URL],
        identity_fields=["/code"],
        target_records=2,
    )


class TestHtmlTable(TestCase):
    def test_declared_columns_keys_and_proofs(self):
        spec = task()
        assert spec.html_table is not None
        html = page(ROW, SKIP, HIDDEN, OTHER)
        captured = html_table_snapshot(html, URL, 10_000, spec.html_table)
        rows = html_table_candidates(captured, spec.html_table)
        assert [row.record for row in rows] == [
            {"code": "007", "stock": 0, "note": "https://example.test/"},
            {"code": "002", "stock": -12, "note": "Bench kit"},
        ]
        assert len(captured.sources) == 6
        assert rows[1].evidence["/stock"].quote == "-12"
        assert rows[1].evidence["/stock"].transform == "integer"
        assert rows[0].scope != rows[1].scope
        for row in rows:
            assert verify(row, captured, SCHEMA, spec) == []

    def test_refuses_incomplete_or_ambiguous_layout(self):
        plan = HtmlTableSpec.model_validate(PLAN)
        cases = [
            ("", "table_not_unique"),
            (page(ROW, OTHER) * 2, "table_not_unique"),
            (page(ROW, OTHER, header=""), "table_header_missing"),
            (page(ROW, OTHER, header=HEADER.replace("Unbound", "Note")), "table_headers_ambiguous"),
            (
                page(ROW, OTHER, header=HEADER.replace("Product code", "SKU")),
                "declared_header_missing",
            ),
            (page(ROW), "declared_table_key_missing"),
            (page(ROW, OTHER, OTHER), "duplicate_table_key"),
            (page(ROW.replace("<td>ignore</td>", ""), OTHER), "unsupported_table_layout"),
            (
                page(ROW.replace("<td>-12", '<td colspan="2">-12'), OTHER),
                "unsupported_table_layout",
            ),
            (page(ROW.replace("<td>-12", "<td hidden>-12"), OTHER), "unsupported_table_layout"),
            (
                page(ROW, OTHER).replace("<thead>", "<colgroup><col hidden></colgroup><thead>"),
                "unsupported_table_layout",
            ),
            (page(ROW.replace('scope="row"', 'scope="col"'), OTHER), "unsupported_table_layout"),
            (page(ROW.replace("Bench<br>kit", page(ROW, OTHER)), OTHER), "table_not_unique"),
            (
                page(ROW.replace("Bench<br>kit", "<table><tr><td>x</td></tr></table>"), OTHER),
                "unsupported_table_layout",
            ),
            (page(ROW.replace("Bench<br>kit", "  "), OTHER), "blank_or_oversized_cell"),
            (page(ROW.replace("-12", "+12"), OTHER), "invalid_integer_cell"),
            (page(ROW.replace("-12", "-9223372036854775809"), OTHER), "invalid_integer_cell"),
        ]
        for html, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(HtmlTableError, reason):
                literal_table_rows(html, plan)

    def test_integer_keys_use_exact_decimal_text(self):
        plan = HtmlTableSpec(
            selector="table",
            fields={"k": {"header": "Key", "value_type": "integer"}},
            key_field="k",
            keys=[1],
        )
        table = "<table><tr><th>Key</th></tr><tr><td>01</td></tr><tr><td>1-9</td></tr>{}</table>"
        with self.assertRaisesRegex(HtmlTableError, "declared_table_key_missing"):
            literal_table_rows(table.format(""), plan)
        assert literal_table_rows(table.format("<tr><td>1</td></tr>"), plan) == [["1"]]

    def test_declared_rows_late_in_the_table_are_not_omitted(self):
        plan = HtmlTableSpec.model_validate(PLAN)
        unrelated = [
            f"<tr><td>Unselected</td><td>not-an-integer</td><td>{i}</td><td></td></tr>"
            for i in range(1000, 1500)
        ]
        assert literal_table_rows(page(ROW, *unrelated, OTHER), plan) == [
            ["007", "https://example.test/", "0"],
            ["002", "Bench kit", "-12"],
        ]

    def test_evidence_budget_includes_portable_snapshot_copies(self):
        plan = HtmlTableSpec.model_validate({**PLAN, "keys": [f"K{i}" for i in range(100)]})
        rows = [
            f"<tr><td>{'é' * 600}</td><td>0</td><td>{key}</td><td></td></tr>" for key in plan.keys
        ]
        with self.assertRaisesRegex(HtmlTableError, "table_evidence_limit"):
            html_table_snapshot(page(*rows), URL, 2_000_000, plan)
        with self.assertRaisesRegex(HtmlTableError, "table_evidence_limit"):
            html_table_snapshot(page(ROW, OTHER), URL, 20, HtmlTableSpec.model_validate(PLAN))

    def test_binding_replay_rejects_another_row_or_changed_plan(self):
        spec = task()
        assert spec.html_table is not None
        captured = html_table_snapshot(page(ROW, OTHER), URL, 10_000, spec.html_table)
        first, second = html_table_candidates(captured, spec.html_table)
        cross_row = first.model_copy(
            update={"evidence": {**first.evidence, "/note": second.evidence["/note"]}}
        )
        assert verify(cross_row, captured, SCHEMA, spec) == ["html_table_binding_mismatch"]
        for wrong in (0.0, False):
            wrong_type = first.model_copy(update={"record": {**first.record, "stock": wrong}})
            assert verify(wrong_type, captured, SCHEMA, spec)
        altered = deepcopy(PLAN)
        altered["fields"]["note"]["header"] = "Unbound"
        rebound = task(HtmlTableSpec.model_validate(altered))
        assert verify(first, captured, SCHEMA, rebound) == ["html_table_snapshot_invalid"]
        foreign_task = spec.model_copy(update={"seed_urls": ["https://example.test/other"]})
        assert verify(first, captured, SCHEMA, foreign_task) == ["html_table_binding_mismatch"]
        incomplete = captured.model_copy(update={"sources": captured.sources[1:]})
        assert verify(first, incomplete, SCHEMA, spec) == ["html_table_snapshot_invalid"]

    def test_preflight_preserves_the_explicit_contract(self):
        spec = task()
        assert "html_table" not in TaskSpec().model_dump()
        assert TaskSpec.model_validate_json(spec.model_dump_json()) == spec
        validate_research_contract(SCHEMA, spec)
        validate_research_contract({"type": "array", "items": SCHEMA}, spec)
        for update in ({"target_records": 1}, {"identity_fields": ["/note"]}, {"seed_urls": []}):
            with (
                self.subTest(update=update),
                self.assertRaisesRegex(VerboisyError, "canonical seed"),
            ):
                validate_research_contract(SCHEMA, spec.model_copy(update=update))
        wrong_type = {**SCHEMA, "properties": {**SCHEMA["properties"], "stock": {"type": "number"}}}
        with self.assertRaisesRegex(VerboisyError, "matching string or integer"):
            validate_research_contract(wrong_type, spec)
        with self.assertRaisesRegex(ValidationError, "other source rules"):
            TaskSpec.model_validate({**spec.model_dump(), "pagination_selector": "a.next"})
        for update in ({"selector": "main table"}, {"keys": ["007", "007"]}, {"keys": [7]}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                HtmlTableSpec.model_validate({**PLAN, **update})
