# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Typed worksheet tables with explicit headers; formulas and style inference are excluded."""

import math
import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any, cast
from xml.etree import ElementTree

from verboisy.extractor.format_errors import DatasetParseError
from verboisy.extractor.office_package import office_package, xml_part

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _cell(cell: ElementTree.Element, strings: list[str]) -> Any:
    if cell.find(S + "f") is not None:
        raise DatasetParseError("XLSX formulas require a separate evaluation contract")
    kind = cell.get("t", "n")
    value = cell.findtext(S + "v")
    if kind == "inlineStr":
        return "".join(
            node.text or ""
            for node in cell.findall(S + "is/" + S + "t")
            + cell.findall(S + "is/" + S + "r/" + S + "t")
        )
    if kind in {"str", "d"}:
        return value or ""
    if kind == "s":
        if (
            value is None
            or not value.isascii()
            or not value.isdecimal()
            or len(value) > 6
            or int(value) >= len(strings)
        ):
            raise DatasetParseError("Invalid XLSX shared string index")
        return strings[int(value)]
    if kind == "b":
        if value not in {"0", "1"}:
            raise DatasetParseError("Invalid XLSX boolean")
        return value == "1"
    if kind != "n":
        raise DatasetParseError("Unsupported XLSX cell type")
    if value is None:
        return None
    # Integer lexemes must bypass float conversion: identifiers and large counts
    # would otherwise lose precision above the IEEE-754 exact-integer boundary.
    try:
        number = int(value) if re.fullmatch(r"[+-]?[0-9]+", value) else float(value)
    except ValueError:
        raise DatasetParseError("Invalid XLSX number") from None
    if isinstance(number, float) and not math.isfinite(number):
        raise DatasetParseError("Non-finite XLSX number")
    return number


def xlsx_rows(content: bytes, max_depth: int) -> Iterator[tuple[dict[str, Any], str]]:
    with office_package(content) as package:
        workbook = xml_part(package, "xl/workbook.xml", max_depth)
        relationships = xml_part(package, "xl/_rels/workbook.xml.rels", max_depth)
        if workbook.tag != S + "workbook" or relationships.tag != P + "Relationships":
            raise DatasetParseError("Unsupported XLSX workbook structure")
        targets: dict[str, str] = {}
        for relation in relationships:
            identity, target = relation.get("Id", ""), relation.get("Target", "")
            if (
                not identity
                or identity in targets
                or not target
                or relation.get("TargetMode") == "External"
                or "\\" in target
                or ".." in PurePosixPath(target).parts
            ):
                raise DatasetParseError("Unsupported XLSX workbook relationship")
            targets[identity] = target.lstrip("/") if target.startswith("/") else "xl/" + target
        strings = []
        if "xl/sharedStrings.xml" in package.namelist():
            shared = xml_part(package, "xl/sharedStrings.xml", max_depth)
            strings = [
                "".join(
                    node.text or ""
                    for node in item.findall(S + "t") + item.findall(S + "r/" + S + "t")
                )
                for item in shared.findall(S + "si")
            ]
        sheets = workbook.findall(S + "sheets/" + S + "sheet")
        if not sheets:
            raise DatasetParseError("XLSX workbook has no worksheets")
        seen = set()
        for sheet in sheets:
            name, identity = sheet.get("name", ""), sheet.get(R + "id", "")
            if not name or name.casefold() in seen or identity not in targets:
                raise DatasetParseError("Ambiguous XLSX worksheet identity")
            seen.add(name.casefold())
            part = targets[identity]
            worksheet = xml_part(package, part, max_depth)
            if worksheet.tag != S + "worksheet":
                raise DatasetParseError("Unsupported XLSX worksheet structure")
            headers: list[str] = []
            previous = 0
            for row in worksheet.findall(S + "sheetData/" + S + "row"):
                number = row.get("r", "")
                if (
                    not number.isascii()
                    or not number.isdecimal()
                    or len(number) > 7
                    or not previous < int(number) <= 1_048_576
                ):
                    raise DatasetParseError("Invalid XLSX row order")
                previous = int(number)
                cells: dict[int, Any] = {}
                for cell in row.findall(S + "c"):
                    address = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", cell.get("r", ""))
                    if address is None or int(address[2]) != previous:
                        raise DatasetParseError("Invalid XLSX cell address")
                    column = 0
                    for character in address[1]:
                        column = column * 26 + ord(character) - ord("A") + 1
                    if column > 1024 or column in cells:
                        raise DatasetParseError("Ambiguous or oversized XLSX row")
                    cells[column] = _cell(cell, strings)
                if not headers:
                    values = [cells.get(index) for index in range(1, max(cells, default=0) + 1)]
                    if (
                        not values
                        or any(not isinstance(item, str) or not item.strip() for item in values)
                        or len(set(values)) != len(values)
                    ):
                        raise DatasetParseError("XLSX first row requires unique text headers")
                    headers = cast(list[str], values)
                    continue
                if max(cells, default=0) > len(headers):
                    raise DatasetParseError("XLSX row extends beyond its headers")
                yield (
                    {
                        "sheet": name,
                        "values": {
                            header: cells.get(index) for index, header in enumerate(headers, 1)
                        },
                    },
                    f"/{part}/rows/{previous}",
                )
