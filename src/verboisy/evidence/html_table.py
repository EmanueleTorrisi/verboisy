# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Select exact keys and columns from one explicitly declared rendered row table."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verboisy.evidence.html_metadata import (
    _FIELD,
    _HIDDEN,
    MAX_TEXT_CHARS,
    HtmlMetadataError,
    _matching,
    _Node,
    _parse_rendered_html,
    _selector,
    _space,
)

MAX_TABLE_KEYS = 100
MAX_TABLE_KEY_CHARS = 256
_INTEGER = re.compile(r"(?:0|-?[1-9][0-9]{0,18})")
_ROW_GROUPS = {"thead", "tbody", "tfoot"}
_TEXT_BREAKS = {"br", "div", "li", "ol", "p", "ul"}


class HtmlTableError(ValueError):
    """A declared table could not provide the requested literal evidence."""


class HtmlTableField(BaseModel):
    """Bind one field to an exact visible header and an explicit scalar type."""

    model_config = ConfigDict(extra="forbid", strict=True)

    header: str = Field(min_length=1, max_length=128)
    value_type: Literal["text", "integer"] = "text"

    @field_validator("header")
    @classmethod
    def normalized_header(cls, value: str) -> str:
        if value != _space(value):
            raise ValueError("Table headers require nonblank text with normalized whitespace")
        return value


class HtmlTableSpec(BaseModel):
    """A simple table selector, column bindings and a bounded set of exact row keys."""

    model_config = ConfigDict(extra="forbid", strict=True)

    selector: str = Field(min_length=1, max_length=128)
    fields: dict[str, HtmlTableField] = Field(min_length=1, max_length=16)
    key_field: str = Field(min_length=1, max_length=64)
    keys: list[int | str] = Field(min_length=1, max_length=MAX_TABLE_KEYS)

    @field_validator("selector")
    @classmethod
    def table_selector(cls, value: str) -> str:
        if _selector(value)[0] != "table":
            raise ValueError("Select a table by tag, optionally with its ID or class")
        return value

    @model_validator(mode="after")
    def validate_bindings(self) -> HtmlTableSpec:
        if any(name == "id" or _FIELD.fullmatch(name) is None for name in self.fields):
            raise ValueError("Use flat field names; id is reserved for generated output metadata")
        if len({item.header for item in self.fields.values()}) != len(self.fields):
            raise ValueError("Each table field requires a distinct header")
        binding = self.fields.get(self.key_field)
        if binding is None or len(set(self.keys)) != len(self.keys):
            raise ValueError("Declare a bound key field and distinct keys")
        for key in self.keys:
            if binding.value_type == "integer":
                if not isinstance(key, int) or not -(2**63) <= key < 2**63:
                    raise ValueError("Integer keys require signed 64-bit JSON integers")
            elif (
                not isinstance(key, str)
                or not 1 <= len(key) <= MAX_TABLE_KEY_CHARS
                or key != _space(key)
            ):
                raise ValueError("Text keys require nonblank text with normalized whitespace")
        return self


def table_value(text: str, binding: HtmlTableField) -> str | int:
    """Replay an observed cell exactly, with no inferred units or numeric formats."""
    if not text or len(text) > MAX_TEXT_CHARS or text != _space(text):
        raise HtmlTableError("blank_or_oversized_cell")
    if binding.value_type == "text":
        return text
    if _INTEGER.fullmatch(text) is None:
        raise HtmlTableError("invalid_integer_cell")
    number = int(text)
    if not -(2**63) <= number < 2**63:
        raise HtmlTableError("invalid_integer_cell")
    return number


def _children(node: _Node) -> list[_Node]:
    result = []
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag not in _HIDDEN:
                result.append(child)
        elif child.strip():
            raise HtmlTableError("unsupported_table_layout")
    return result


def _table_rows(table: _Node) -> list[tuple[bool, list[_Node]]]:
    rows: list[_Node] = []
    for child in _children(table):
        if child.tag in _ROW_GROUPS:
            rows.extend(_children(child))
        elif child.tag == "tr":
            rows.append(child)
        elif child.tag == "colgroup":
            if child.hidden or any(column.hidden for column in _children(child)):
                raise HtmlTableError("unsupported_table_layout")
        elif child.tag != "caption" and not child.hidden:
            raise HtmlTableError("unsupported_table_layout")
    result = []
    for row in rows:
        if row.tag != "tr":
            if row.hidden:
                continue
            raise HtmlTableError("unsupported_table_layout")
        cells = _children(row)
        if any(cell.spanning for cell in cells):
            raise HtmlTableError("unsupported_table_layout")
        if row.hidden:
            continue
        # Hidden cells cannot be dropped independently: doing so could move a
        # different physical column underneath a declared header.
        if not cells or any(cell.hidden or cell.tag not in {"td", "th"} for cell in cells):
            raise HtmlTableError("unsupported_table_layout")
        result.append((all(cell.tag == "th" and not cell.row_header for cell in cells), cells))
    return result


def _cell_text(cell: _Node) -> str:
    pieces: list[str] = []
    todo: list[_Node | str] = [cell]
    while todo:
        child = todo.pop()
        if isinstance(child, str):
            pieces.append(child)
        elif not child.hidden:
            if child.tag in _TEXT_BREAKS:
                pieces.append(" ")
                todo.append(" ")
            todo.extend(reversed(child.children))
    result = _space("".join(pieces))
    if len(result) > MAX_TEXT_CHARS:
        raise HtmlTableError("blank_or_oversized_cell")
    return result


def literal_table_rows(html: str, plan: HtmlTableSpec) -> list[list[str]]:
    """Return cell texts in declared key and sorted field order, or refuse the whole table."""
    try:
        root = _parse_rendered_html(html, keep_hidden=True)
    except HtmlMetadataError as error:
        raise HtmlTableError(str(error)) from error
    tables = _matching(root, plan.selector)
    if len(tables) != 1:
        raise HtmlTableError("table_not_unique")
    if len(_matching(tables[0], "table")) != 1:
        raise HtmlTableError("unsupported_table_layout")
    rows = _table_rows(tables[0])
    if not rows or not rows[0][0]:
        raise HtmlTableError("table_header_missing")
    headers = [_cell_text(cell) for cell in rows[0][1]]
    if "" in headers or len(set(headers)) != len(headers):
        raise HtmlTableError("table_headers_ambiguous")
    column_by_header = {header: index for index, header in enumerate(headers)}
    if any(binding.header not in column_by_header for binding in plan.fields.values()):
        raise HtmlTableError("declared_header_missing")
    bindings = sorted(plan.fields.items())
    columns = [column_by_header[binding.header] for _, binding in bindings]
    key_column = column_by_header[plan.fields[plan.key_field].header]
    keys = [str(key) for key in plan.keys]
    wanted = set(keys)
    selected: dict[str, list[str]] = {}
    for header, cells in rows[1:]:
        if (
            header
            or len(cells) != len(headers)
            or any(
                cell.tag == "th" and not (cell.row_header and index == key_column)
                for index, cell in enumerate(cells)
            )
        ):
            raise HtmlTableError("unsupported_table_layout")
        key = _cell_text(cells[key_column])
        if key not in wanted:
            continue
        if key in selected:
            raise HtmlTableError("duplicate_table_key")
        values = [_cell_text(cells[index]) for index in columns]
        for (_, binding), value in zip(bindings, values, strict=True):
            table_value(value, binding)
        selected[key] = values
    if selected.keys() != wanted:
        raise HtmlTableError("declared_table_key_missing")
    return [selected[key] for key in keys]
