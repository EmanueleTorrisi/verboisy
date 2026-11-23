# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Keep observed headers with values from unambiguous rectangular HTML tables."""

from bs4 import Tag


def _rows(table: Tag) -> list[Tag]:
    result: list[Tag] = []
    for child in table.find_all(["tr", "thead", "tbody", "tfoot"], recursive=False):
        if child.name == "tr":
            result.append(child)
        else:
            result.extend(child.find_all("tr", recursive=False))
    return result


def _cells(row: Tag) -> list[Tag]:
    return row.find_all(["th", "td"], recursive=False)


def _spans(cell: Tag) -> bool:
    return cell.has_attr("rowspan") or cell.has_attr("colspan")


def table_column_labels(container: Tag, obstructed: set[int]) -> dict[int, str]:
    """Map observed cells to labels; leave complex or ambiguous tables unlabeled."""
    labels: dict[int, str] = {}
    for table in container.find_all("table"):
        rows = _rows(table)
        if id(table) in obstructed or len(rows) < 2 or table.find("table") is not None:
            continue
        header = _cells(rows[0])
        if not header or any(
            cell.name != "th" or _spans(cell) or cell.get("scope") not in (None, "col")
            for cell in header
        ):
            continue
        names = [" ".join(cell.get_text(" ", strip=True).split()) for cell in header]
        if any(not 1 <= len(name) <= 128 for name in names) or len(
            {name.casefold() for name in names}
        ) != len(names):
            continue
        body = [_cells(row) for row in rows[1:]]
        if any(
            len(cells) != len(names)
            or any(
                _spans(cell) or (cell.name == "th" and (index != 0 or cell.get("scope") != "row"))
                for index, cell in enumerate(cells)
            )
            for cells in body
        ):
            continue
        for cells in body:
            labels.update((id(cell), name) for cell, name in zip(cells, names, strict=True))
    return labels


def observed_column(node: Tag, labels: dict[int, str]) -> str | None:
    if not labels:
        return None
    cell = node if node.name in ("td", "th") else node.find_parent(["td", "th"])
    return labels.get(id(cell))
