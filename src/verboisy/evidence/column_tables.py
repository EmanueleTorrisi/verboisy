# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Literal evidence for explicitly declared column-oriented HTML tables.

No orientation is inferred. Physical column boundaries define entity scopes;
row labels are repeated as observed context within those scopes. IDs retain
one-based table, row and column coordinates. Values and links are not rewritten.
"""

from collections.abc import Callable

from bs4 import Tag

from verboisy.evidence.models import ColumnTableSpec, Source

MAX_TABLE_CELLS = 16384
MAX_TABLE_COLUMNS = 64
MAX_CONTEXT_CHARS = 512


def _text(cell: Tag) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def _signature(cell: Tag) -> tuple[str, tuple[str, ...]]:
    return _text(cell), tuple(str(link["href"]) for link in cell.select("a[href]"))


def _grid(table: Tag) -> list[list[Tag]]:
    if table.find("table") is not None or table.find_parent("table") is not None:
        raise ValueError("column_table_nested")
    if table.select("article, li, [itemscope], [data-record]"):
        raise ValueError("column_table_nested_entities")
    rows = [list(row.find_all(["td", "th"], recursive=False)) for row in table.find_all("tr")]
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError("column_table_empty")
    if len(rows[0]) > MAX_TABLE_COLUMNS:
        raise ValueError("column_table_column_limit")
    if sum(len(row) for row in rows) > MAX_TABLE_CELLS:
        raise ValueError("column_table_cell_limit")
    if any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("column_table_ragged")
    for row in rows:
        for cell in row:
            if any(str(cell.get(name, "1")).strip() != "1" for name in ("colspan", "rowspan")):
                raise ValueError("column_table_spanning_cell")
    headers = [_text(cell) for cell in rows[0]]
    if headers[0] or any(not header for header in headers[1:]):
        raise ValueError("column_table_header_shape")
    if any(len(header) > MAX_CONTEXT_CHARS for header in headers):
        raise ValueError("column_table_context_limit")
    if len({header.casefold() for header in headers[1:]}) != len(headers) - 1:
        raise ValueError("column_table_duplicate_headers")
    original = [_signature(cell) for cell in rows[0]]
    labels: set[str] = set()
    for row in rows[1:]:
        if [_signature(cell) for cell in row] == original:
            continue
        label = _text(row[0]).casefold()
        if not label or label in labels:
            raise ValueError("column_table_attribute_labels")
        if len(label) > MAX_CONTEXT_CHARS:
            raise ValueError("column_table_context_limit")
        labels.add(label)
    if not labels:
        raise ValueError("column_table_empty")
    return rows


def column_table_sources(
    container: Tag,
    declarations: list[ColumnTableSpec],
    url: str,
    canonicalize: Callable[[str, str], str | None],
) -> tuple[set[int], list[Source]]:
    """Return replaced DOM nodes and literal sources; reject ambiguous layouts."""
    excluded: set[int] = set()
    sources: list[Source] = []
    if not declarations:
        return excluded, sources
    tables = container.find_all("table")
    seen: set[int] = set()
    for declaration in declarations:
        number = declaration.table
        if number in seen or number > len(tables):
            raise ValueError("column_table_missing_or_repeated")
        seen.add(number)
        table = tables[number - 1]
        rows = _grid(table)
        excluded.update(id(node) for node in [table, *table.find_all(True)])
        original = [_signature(cell) for cell in rows[0]]
        selected_rows = [
            (row_number, row, _text(row[0]))
            for row_number, row in enumerate(rows, 1)
            if row_number == 1 or [_signature(cell) for cell in row] != original
        ]
        for column in range(1, len(rows[0])):
            scope = f"table{number}.column{column + 1}"
            for row_number, row, label in selected_rows:
                prefix = f"table{number}.row{row_number}.column{column + 1}"
                if row_number > 1:
                    sources.append(
                        Source(id=prefix + ".label", kind="text", text=label, scope=scope)
                    )
                cell = row[column]
                text = _text(cell)
                if text:
                    sources.append(
                        Source(id=prefix + ".value", kind="text", text=text, scope=scope)
                    )
                for index, link in enumerate(cell.select("a[href]"), 1):
                    href = canonicalize(str(link["href"]), url)
                    if href is not None:
                        sources.append(
                            Source(
                                id=prefix + f".link{index}",
                                kind="link",
                                text=_text(link),
                                href=href,
                                scope=scope,
                            )
                        )
    return excluded, sources
