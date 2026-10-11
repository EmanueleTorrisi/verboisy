# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Office values, locators and rejection boundaries use controlled real ZIP/XML parts."""

import io
import stat
import warnings
import zipfile
import zlib
from xml.etree import ElementTree

import pytest
from verboisy.extractor.dataset import DatasetParseError, parse_dataset
from verboisy.extractor.office_package import office_package, xml_part
from verboisy.extractor.xlsx import _cell

from tests.test_extractor.office_fixtures import (
    P,
    S,
    W,
    archive,
    cell,
    document,
    workbook_parts,
    worksheet,
)


def test_docx_paragraphs_tabs_breaks_tables_and_empty_text():
    raw = document(
        "<w:p><w:r><w:t>Anaïs</w:t><w:tab/><w:t/><w:br/><w:cr/></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>李雷</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p/>"
    )
    parsed = parse_dataset(raw, "docx")
    assert [r.values for r in parsed.rows] == [
        {"text": "Anaïs\t\n\n"},
        {"text": "李雷"},
        {"text": ""},
    ]
    assert [r.source_pointer for r in parsed.rows] == [
        f"/word/document.xml/paragraphs/{i}" for i in (1, 2, 3)
    ]
    assert parsed.original_bytes == raw
    with pytest.raises(DatasetParseError, match="row limit"):
        parse_dataset(raw, "docx", max_rows=2)


@pytest.mark.parametrize(
    "xml", [f'<w:document xmlns:w="{W}"/>', f'<w:other xmlns:w="{W}"><w:body/></w:other>']
)
def test_docx_requires_document_body(xml):
    with pytest.raises(DatasetParseError, match="supported body"):
        parse_dataset(archive({"word/document.xml": xml}), "docx")


def test_xlsx_typed_values_sparse_rows_multiple_sheets_and_phonetic_guides():
    headers = "".join(
        cell(f"{c}1", v)
        for c, v in zip(
            "ABCDEFG",
            ["name", "integer", "decimal", "bool", "date", "serial", "empty"],
            strict=True,
        )
    )
    cells = (
        cell("A3", "0", "s")
        + cell("B3", "9007199254740993", "n")
        + cell("C3", "2.5", "n")
        + cell("D3", "1", "b")
        + cell("E3", "2026-10-10", "d")
        + cell("F3", "45000", "n")
    )
    parts = workbook_parts(f'<row r="1">{headers}</row><row r="3">{cells}</row><row r="4"/>')
    parts["xl/sharedStrings.xml"] = (
        f'<sst xmlns="{S}"><si><r><t>Ana</t></r><r><t>ïs</t></r>'
        "<rPh><t>ignored phonetic</t></rPh></si></sst>"
    )
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        "</sheets>", '<sheet name="Other" r:id="r2"/></sheets>'
    )
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        "</Relationships>",
        '<Relationship Id="r2" Target="/xl/worksheets/sheet2.xml"/></Relationships>',
    )
    parts["xl/worksheets/sheet2.xml"] = worksheet(
        '<row r="1">' + cell("A1", "name") + '</row><row r="2">' + cell("A2", "Bob") + "</row>"
    )
    parsed = parse_dataset(archive(parts), "xlsx")
    assert parsed.rows[0].values == {
        "sheet": "People",
        "values": dict(
            zip(
                ["name", "integer", "decimal", "bool", "date", "serial", "empty"],
                ["Anaïs", 9007199254740993, 2.5, True, "2026-10-10", 45000, None],
                strict=True,
            )
        ),
    }
    assert set(parsed.rows[1].values["values"].values()) == {None}
    assert parsed.rows[2].values == {"sheet": "Other", "values": {"name": "Bob"}}
    assert parsed.rows[0].source_pointer == "/xl/worksheets/sheet1.xml/rows/3"


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("str", "", ""),
        ("d", "", ""),
        ("s", "0", "literal"),
        ("b", "0", False),
        ("n", "1e2", 100.0),
        ("n", "-12", -12),
        ("inlineStr", "", ""),
    ],
)
def test_supported_cell_kinds(kind, value, expected):
    node = ElementTree.fromstring(f'<c xmlns="{S}" t="{kind}"><v>{value}</v></c>')
    assert _cell(node, ["literal"]) == expected
    assert _cell(ElementTree.fromstring(f'<c xmlns="{S}"/>'), []) is None
    assert (
        _cell(
            ElementTree.fromstring(
                f'<c xmlns="{S}" t="inlineStr"><is><r><t>rich</t></r><r><t/></r></is></c>'
            ),
            [],
        )
        == "rich"
    )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("s", None),
        ("s", "\uff11"),
        ("s", "-1"),
        ("s", "1"),
        ("s", "1234567"),
        ("b", "2"),
        ("e", "#REF!"),
        ("n", "wrong"),
        ("n", "NaN"),
        ("n", "1e999"),
    ],
)
def test_invalid_cell_values(kind, value):
    inner = "" if value is None else f"<v>{value}</v>"
    with pytest.raises(DatasetParseError):
        _cell(ElementTree.fromstring(f'<c xmlns="{S}" t="{kind}">{inner}</c>'), ["one"])


def test_formula_cache_is_never_used():
    raw = archive(
        workbook_parts(
            '<row r="1">'
            + cell("A1", "name")
            + '</row><row r="2">'
            + cell("A2", "2", "n", "<f>1+1</f>")
            + "</row>"
        )
    )
    with pytest.raises(DatasetParseError, match="formulas"):
        parse_dataset(raw, "xlsx")


@pytest.mark.parametrize(
    "row",
    [
        "<row/>",
        '<row r="\uff11"/>',
        '<row r="0"/>',
        '<row r="12345678"/>',
        '<row r="1048577"/>',
        '<row r="1"/>',
        '<row r="2"><c r="bad"/></row>',
        '<row r="2"><c r="A3"/></row>',
        '<row r="2"><c r="ZZZ2"/></row>',
        '<row r="2"><c r="A2"/><c r="A2"/></row>',
        '<row r="2"><c r="B2"/></row>',
    ],
)
def test_invalid_rows_addresses_and_width(row):
    raw = archive(workbook_parts('<row r="1">' + cell("A1", "name") + "</row>" + row))
    with pytest.raises(DatasetParseError):
        parse_dataset(raw, "xlsx")


@pytest.mark.parametrize(
    "headers",
    [
        "",
        cell("A1", ""),
        cell("A1", "3", "n"),
        cell("B1", "gap"),
        cell("A1", "name") + cell("B1", "name"),
    ],
)
def test_ambiguous_headers_are_rejected(headers):
    with pytest.raises(DatasetParseError, match="unique text headers"):
        parse_dataset(archive(workbook_parts(f'<row r="1">{headers}</row>')), "xlsx")


@pytest.mark.parametrize(
    "change",
    [
        "workbook",
        "relationships",
        "empty",
        "blank_name",
        "duplicate_sheet",
        "unknown_id",
        "worksheet",
    ],
)
def test_workbook_structure_and_sheet_identity(change):
    parts = workbook_parts()
    if change == "workbook":
        parts["xl/workbook.xml"] = "<other/>"
    elif change == "relationships":
        parts["xl/_rels/workbook.xml.rels"] = "<other/>"
    elif change == "empty":
        parts["xl/workbook.xml"] = f'<workbook xmlns="{S}"/>'
    elif change == "blank_name":
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace('name="People"', 'name=""')
    elif change == "duplicate_sheet":
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
            "</sheets>", '<sheet name="people" r:id="r1"/></sheets>'
        )
    elif change == "unknown_id":
        parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace('r:id="r1"', 'r:id="missing"')
    else:
        parts["xl/worksheets/sheet1.xml"] = "<other/>"
    with pytest.raises(DatasetParseError):
        parse_dataset(archive(parts), "xlsx")


@pytest.mark.parametrize(
    "relation",
    [
        '<Relationship Target="a"/>',
        '<Relationship Id="r1"/>',
        '<Relationship Id="r1" Target="a" TargetMode="External"/>',
        '<Relationship Id="r1" Target="a\\b"/>',
        '<Relationship Id="r1" Target="../a"/>',
        '<Relationship Id="r1" Target="a"/><Relationship Id="r1" Target="b"/>',
    ],
)
def test_unsafe_or_ambiguous_relationships(relation):
    parts = workbook_parts()
    parts["xl/_rels/workbook.xml.rels"] = f'<Relationships xmlns="{P}">{relation}</Relationships>'
    with pytest.raises(DatasetParseError, match="relationship"):
        parse_dataset(archive(parts), "xlsx")


@pytest.mark.parametrize(
    "raw",
    [
        b"not a zip",
        archive({}),
        archive({"word/document.xml": b"\xff"}),
        archive({"word/document.xml": "<broken"}),
        archive({"word/document.xml": "<!DOCTYPE document><document/>"}),
        archive({"word/document.xml": '<!ENTITY x "xx"><document/>'}),
    ],
)
def test_malformed_archive_and_xml(raw):
    with pytest.raises(DatasetParseError):
        parse_dataset(raw, "docx")


@pytest.mark.parametrize("name", ["/absolute", "a\\b", "C:drive", "a/../b"])
def test_archive_members_are_not_extracted(name):
    with pytest.raises(DatasetParseError, match="Unsafe"):
        parse_dataset(archive({name: "x"}), "docx")


def test_symlinks_duplicate_members_and_unsupported_compression():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as package:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        package.writestr(info, "outside")
    with pytest.raises(DatasetParseError, match="Unsafe"):
        parse_dataset(out.getvalue(), "docx")
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(out, "w") as package:
            package.writestr("same", "a")
            package.writestr("same", "b")
    with pytest.raises(DatasetParseError, match="Duplicate"):
        parse_dataset(out.getvalue(), "docx")
    with pytest.raises(DatasetParseError, match="encoding"):
        parse_dataset(archive({"file": "x"}, zipfile.ZIP_BZIP2), "docx")


def test_archive_and_xml_resource_limits():
    for raw in [archive({str(i): "" for i in range(1025)}), archive({"huge": b"x" * 16_777_217})]:
        with pytest.raises(DatasetParseError, match="expansion"):
            parse_dataset(raw, "docx", max_bytes=32_000_000)
    with pytest.raises(DatasetParseError, match="ratio"):
        parse_dataset(archive({"huge": "x" * 100_000}, zipfile.ZIP_DEFLATED), "docx")
    with pytest.raises(DatasetParseError, match="structure limit"):
        parse_dataset(document(), "docx", max_depth=2)
    with (
        office_package(archive({"part": "<root>" + "<x/>" * 100_000 + "</root>"})) as package,
        pytest.raises(DatasetParseError, match="structure limit"),
    ):
        xml_part(package, "part", 32)


@pytest.mark.parametrize("failure", [OSError, RuntimeError, zipfile.BadZipFile, zlib.error])
def test_encryption_and_read_failure_are_controlled(monkeypatch, failure):
    raw = bytearray(archive({"word/document.xml": "<document/>"}))
    offset = raw.index(b"PK\x01\x02")
    raw[offset + 8] |= 1
    with pytest.raises(DatasetParseError, match="encoding"):
        parse_dataset(bytes(raw), "docx")

    def fail(*args, **kwargs):
        raise failure("unreadable archive")

    monkeypatch.setattr(zipfile.ZipFile, "read", fail)
    with pytest.raises(DatasetParseError, match="Malformed office archive"):
        parse_dataset(document(), "docx")
