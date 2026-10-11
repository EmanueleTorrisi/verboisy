# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Small OOXML packages with controllable parts for parser and workflow regressions."""

import io
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def archive(parts, compression=zipfile.ZIP_STORED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return out.getvalue()


def document(body="<w:p><w:r><w:t>Anaïs</w:t></w:r></w:p>"):
    return archive(
        {"word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'}
    )


def cell(address, value="", kind="inlineStr", extra=""):
    inner = f"<is><t>{value}</t></is>" if kind == "inlineStr" else f"<v>{value}</v>"
    return f'<c r="{address}" t="{kind}">{extra}{inner}</c>'


def worksheet(rows):
    return f'<worksheet xmlns="{S}"><sheetData>{rows}</sheetData></worksheet>'


def workbook_parts(rows=None):
    if rows is None:
        rows = (
            '<row r="1">'
            + cell("A1", "name")
            + '</row><row r="2">'
            + cell("A2", "Anaïs")
            + "</row>"
        )
    return {
        "xl/workbook.xml": (
            f'<workbook xmlns="{S}" xmlns:r="{R}">'
            '<sheets><sheet name="People" r:id="r1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{P}">'
            '<Relationship Id="r1" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": worksheet(rows),
    }
