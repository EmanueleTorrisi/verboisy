# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Declared column entities retain literal evidence and isolation boundaries."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError
from verboisy.evidence.column_tables import column_table_sources
from verboisy.evidence.models import Candidate, ColumnTableSpec, Proof, TaskSpec
from verboisy.evidence.snapshot import canonical_url, chunks, snapshot
from verboisy.evidence.verify import verify

URL = "https://nssdc.gsfc.nasa.gov/planetary/factsheet/"
NASA = Path(__file__).parents[1] / "fixtures/pages/nasa_planetary_factsheet.html"
TABLE = (
    '<table><tr><td></td><th><a href="/alpha">ALPHA</a></th><th>BETA</th></tr>'
    "<tr><th>Size (km)</th><td>1,234</td><td>9</td></tr>"
    "<tr><th>Count</th><td>0</td><td>0</td></tr></table>"
)
DECLARED = [ColumnTableSpec(table=1)]


def declared(html=TABLE, **kwargs):
    return snapshot(html, URL, column_tables=DECLARED, **kwargs)


def test_nasa_capture_and_cross_planet_grounding():
    raw = NASA.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "42bdc3f1dae470b85580c6ac66c353964a05d544ad2ac970a6b7d908337a6c3c"
    )
    page = declared(raw.decode())
    assert not page.truncated
    assert page.content_hash == hashlib.sha256(raw).hexdigest()
    assert len({s.id for s in page.sources}) == len(page.sources)
    expected = [("MERCURY", 4879, 3.7, 0), ("VENUS", 12104, 8.9, 0), ("EARTH", 12756, 9.8, 1)]
    fields = ("body", "diameter_km", "gravity_m_s2", "number_of_moons")
    schema = {
        "type": "object",
        "properties": {
            "body": {"type": "string"},
            "diameter_km": {"type": "integer"},
            "gravity_m_s2": {"type": "number"},
            "number_of_moons": {"type": "integer"},
        },
        "required": list(fields),
        "additionalProperties": False,
    }
    task = TaskSpec(column_tables=DECLARED, identity_fields=["/body"])
    for column, row in enumerate(expected, 2):
        record = dict(zip(fields, row, strict=True))
        evidence = {}
        for field, physical_row, transform in (
            ("body", 1, "text"),
            ("diameter_km", 3, "integer"),
            ("gravity_m_s2", 5, "number"),
            ("number_of_moons", 19, "integer"),
        ):
            source_id = f"table1.row{physical_row}.column{column}.value"
            source = next(s for s in page.sources if s.id == source_id)
            evidence["/" + field] = Proof(source=source_id, quote=source.text, transform=transform)
        candidate = Candidate(scope=f"table1.column{column}", record=record, evidence=evidence)
        assert verify(candidate, page, schema, task) == []
        # Mercury and Venus both have zero moons: equal values do not permit borrowing evidence.
        if column == 2:
            candidate.evidence["/number_of_moons"].source = "table1.row19.column3.value"
            assert verify(candidate, page, schema, task) == [
                "/number_of_moons:source_outside_entity"
            ]
    legacy = snapshot(raw.decode(), URL)
    body_scopes = {s.scope for s in legacy.sources if s.text == "MERCURY"}
    diameter_scopes = {s.scope for s in legacy.sources if s.text == "4879"}
    assert body_scopes.isdisjoint(diameter_scopes)


def test_literal_labels_links_and_unselected_entities():
    page = declared(TABLE + "<article>OUTSIDE</article><table><tr><td>Other</td></tr></table>")
    sources = {s.id: s for s in page.sources}
    assert sources["table1.row2.column2.label"].text == "Size (km)"
    assert sources["table1.row2.column2.value"].text == "1,234"
    assert sources["table1.row1.column2.link1"].href == "https://nssdc.gsfc.nasa.gov/alpha"
    for name in ("OUTSIDE", "Other"):
        assert all(s.scope.startswith("s") for s in page.sources if s.text == name)
    assert all(s.scope.startswith("table1.") for s in page.sources if s.text == "ALPHA")
    assert {s.id for group in chunks(page, 5000) for s in group} == set(sources)


def test_no_declaration_preserves_row_scopes_and_old_task_json():
    legacy = snapshot(TABLE, URL)
    assert all(not s.scope.startswith("table") for s in legacy.sources)
    assert TaskSpec.model_validate_json('{"identity_fields":["/body"]}').column_tables == []
    task = TaskSpec(column_tables=DECLARED)
    assert TaskSpec.model_validate_json(task.model_dump_json()).column_tables == DECLARED


def test_empty_values_invalid_links_repeated_headers_and_limits():
    html = TABLE.replace('href="/alpha"', 'href="javascript:alert(1)"').replace(
        "<td>9</td>", "<td></td>"
    )
    header = html.split("</tr>", 1)[0].removeprefix("<table>") + "</tr>"
    html = html.replace("</table>", header + "</table>")
    page = declared(html)
    assert not any(s.kind == "link" for s in page.sources)
    assert not any(s.id == "table1.row2.column3.value" for s in page.sources)
    assert not any("row4" in s.id for s in page.sources)
    bounded = declared(html, max_chars=1)
    assert bounded.truncated and not bounded.sources


@pytest.mark.parametrize("value", [0, 101, True, "1"])
def test_table_number_validation(value):
    with pytest.raises(ValidationError):
        ColumnTableSpec(table=value)


def test_duplicate_and_dataset_declarations_rejected():
    with pytest.raises(ValidationError, match="unique table"):
        TaskSpec(column_tables=[*DECLARED, *DECLARED])
    with pytest.raises(ValidationError, match="HTML sources"):
        TaskSpec(
            column_tables=DECLARED,
            dataset_sources=[{"format": "csv", "url": "https://example.test/data.csv"}],
        )


@pytest.mark.parametrize(
    "html,reason",
    [
        ("<p>No table</p>", "missing_or_repeated"),
        ("<table></table>", "empty"),
        ("<table><tr><td></td></tr><tr><td>x</td></tr></table>", "empty"),
        (TABLE.replace("<td>9</td>", ""), "ragged"),
        (TABLE.replace("<td>9</td>", '<td rowspan="2">9</td>'), "spanning_cell"),
        (TABLE.replace("<td>9</td>", '<td colspan="2">9</td>'), "spanning_cell"),
        (TABLE.replace("<td></td>", "<td>Not blank</td>"), "header_shape"),
        (TABLE.replace("<th>BETA</th>", "<th></th>"), "header_shape"),
        (TABLE.replace("BETA", "alpha"), "duplicate_headers"),
        (TABLE.replace("Count", "Size (km)"), "attribute_labels"),
        (TABLE.replace("Count", ""), "attribute_labels"),
        (TABLE.replace("<td>9</td>", "<td><table><tr><td>x</td></tr></table></td>"), "nested"),
        (TABLE.replace("<td>9</td>", "<td><article>9</article></td>"), "nested_entities"),
        (TABLE.replace("<td>9</td>", "<td hidden>9</td>"), "ragged"),
    ],
)
def test_ambiguous_layouts_fail_closed(html, reason):
    with pytest.raises(ValueError, match="column_table_" + reason):
        declared(html)


def test_repeated_header_only_is_empty_and_different_links_are_not_dropped():
    header = TABLE.split("</tr>", 1)[0].removeprefix("<table>") + "</tr>"
    with pytest.raises(ValueError, match="empty"):
        declared("<table>" + header * 2 + "</table>")
    with pytest.raises(ValueError, match="attribute_labels"):
        declared(TABLE.replace("</table>", header.replace("/alpha", "/other") + "</table>"))


def test_limits_nested_selection_and_duplicate_direct_calls(monkeypatch):
    import verboisy.evidence.column_tables as module
    from bs4 import BeautifulSoup

    with pytest.raises(ValueError, match="nested"):
        snapshot(
            "<table><tr><td>" + TABLE + "</td></tr></table>",
            URL,
            column_tables=[ColumnTableSpec(table=2)],
        )
    container = BeautifulSoup(TABLE, "html.parser")
    with pytest.raises(ValueError, match="missing_or_repeated"):
        column_table_sources(container, [*DECLARED, *DECLARED], URL, canonical_url)
    monkeypatch.setattr(module, "MAX_TABLE_CELLS", 8)
    with pytest.raises(ValueError, match="cell_limit"):
        declared()


@pytest.mark.parametrize("field", ["ALPHA", "Count"])
def test_context_amplification_is_bounded(field):
    with pytest.raises(ValueError, match="context_limit"):
        declared(TABLE.replace(field, "x" * 513))


def test_wide_table_limit_and_linear_header_inspection(monkeypatch):
    import verboisy.evidence.column_tables as module

    calls = []
    original = module._signature

    def counted(cell):
        calls.append(cell)
        return original(cell)

    monkeypatch.setattr(module, "_signature", counted)
    html = "<table><tr><td></td>" + "".join(f"<td>P{i}</td>" for i in range(9))
    html += "</tr><tr><td>Count</td>" + "<td>0</td>" * 9 + "</tr></table>"
    assert not declared(html).truncated
    assert len(calls) <= 3 * 20
    monkeypatch.setattr(module, "MAX_TABLE_COLUMNS", 9)
    with pytest.raises(ValueError, match="column_limit"):
        declared(html)
