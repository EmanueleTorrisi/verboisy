# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Observed table labels survive row windowing without becoming new evidence."""

import pytest
from verboisy.evidence.models import Source
from verboisy.evidence.snapshot import chunks, snapshot

URL = "https://catalog.example.test/inspections"


def test_table_labels_travel_with_row_and_link_values():
    page = snapshot(
        "<table><thead><tr><th scope='col'>Machine</th><th>Inspection   expires</th>"
        "<th>Certificate</th></tr></thead><tbody>"
        "<tr><th scope='row'>X2</th><td><time>March 21, 2028</time></td>"
        "<td><a href='/records/x2'>Certificate X2</a></td></tr></tbody></table>"
        "<p>Site summary</p>",
        URL,
    )
    row = [s for s in page.sources if s.scope != "page"]
    assert [(s.text, s.column_header) for s in row] == [
        ("X2", "Machine"),
        ("March 21, 2028", "Inspection expires"),
        ("Certificate X2", "Certificate"),
    ]
    assert len({s.scope for s in row}) == 1 and row[-1].href == URL.replace(
        "/inspections", "/records/x2"
    )
    limit = sum(len(s.model_dump_json()) for s in row)
    row_batch = next(b for b in chunks(page, limit) if row[0] in b)
    assert row_batch == row
    unrelated = next(s for s in page.sources if s.text == "Site summary")
    assert "column_header" not in unrelated.model_dump()
    assert Source.model_validate_json(unrelated.model_dump_json()) == unrelated


@pytest.mark.parametrize(
    "markup",
    [
        "<tr><th>A</th><th>B</th></tr>",
        "<tr><td>A</td><th>B</th></tr><tr><td>x</td><td>y</td></tr>",
        "<tr><th scope='row'>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr>",
        "<tr><th colspan=2>A</th></tr><tr><td>x</td><td>y</td></tr>",
        "<tr><th>A</th><th>a</th></tr><tr><td>x</td><td>y</td></tr>",
        "<tr><th> </th><th>B</th></tr><tr><td>x</td><td>y</td></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><td>x</td></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><td rowspan=2>x</td><td>y</td></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><td>x</td><th scope='row'>y</th></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><th>x</th><td>y</td></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><td>x<table><tr><td>z</td></tr></table></td>"
        "<td>y</td></tr>",
        "<tr><th hidden>A</th><th>B</th></tr><tr><td>x</td><td hidden>y</td></tr>",
        "<tr><th style='display:none'>A</th><th>B</th></tr>"
        "<tr><td>x</td><td style='display:none'>y</td></tr>",
        "<tr><th>A</th><th>B</th></tr><tr><td><span aria-hidden='true'>old</span>x</td>"
        "<td>y</td></tr>",
    ],
)
def test_ambiguous_or_partly_hidden_layout_never_claims_a_column_mapping(markup):
    page = snapshot(f"<table>{markup}</table><p>Outside</p>", URL)
    assert all(s.column_header is None for s in page.sources)
