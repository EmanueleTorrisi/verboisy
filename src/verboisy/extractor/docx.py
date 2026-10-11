# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal main-document paragraphs, preserving order and immutable part locators."""

from collections.abc import Iterator
from typing import Any

from verboisy.extractor.format_errors import DatasetParseError
from verboisy.extractor.office_package import office_package, xml_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_rows(content: bytes, max_depth: int) -> Iterator[tuple[dict[str, Any], str]]:
    with office_package(content) as package:
        root = xml_part(package, "word/document.xml", max_depth)
        body = root.find(W + "body")
        if root.tag != W + "document" or body is None:
            raise DatasetParseError("DOCX main document has no supported body")
        for index, paragraph in enumerate(body.iter(W + "p"), 1):
            parts = []
            for node in paragraph.iter():
                if node.tag == W + "t":
                    parts.append(node.text or "")
                elif node.tag == W + "tab":
                    parts.append("\t")
                elif node.tag in {W + "br", W + "cr"}:
                    parts.append("\n")
            yield {"text": "".join(parts)}, f"/word/document.xml/paragraphs/{index}"
