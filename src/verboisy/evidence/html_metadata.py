# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Deterministic text bindings over one explicitly selected rendered HTML record."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SELECTOR = re.compile(
    r"(?P<tag>[a-z][a-z0-9-]*)?(?:#(?P<id>[A-Za-z_][A-Za-z0-9_-]*))?"
    r"(?:\.(?P<class>[A-Za-z_][A-Za-z0-9_-]*))?"
)
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_HIDDEN = frozenset("head script style noscript template iframe svg math".split())
MAX_HTML_CHARS = 2_000_000
MAX_NODES = 20_000
MAX_DEPTH = 128
MAX_TEXT_CHARS = 8_192


class HtmlMetadataError(ValueError):
    """The declared region did not produce one unambiguous literal record."""


def _selector(value: str) -> tuple[str | None, str | None, str | None]:
    match = _SELECTOR.fullmatch(value)
    if not value or match is None:
        raise ValueError("Use a simple tag, #id or .class selector; combinators are not supported")
    return match["tag"], match["id"], match["class"]


def _space(value: str) -> str:
    return " ".join(value.split())


def _label(value: str) -> str:
    return _space(value).removesuffix(":").rstrip()


class HtmlMetadataField(BaseModel):
    """Select text, or one exact label from a selected definition list."""

    model_config = ConfigDict(extra="forbid", strict=True)

    selector: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, min_length=1, max_length=256)
    on_missing: Literal["error", "null"] = "error"

    @model_validator(mode="after")
    def validate_binding(self) -> HtmlMetadataField:
        tag, _, _ = _selector(self.selector)
        if self.label is not None and (
            tag != "dl" or not _label(self.label) or _space(self.label) != self.label
        ):
            raise ValueError("A definition label needs a dl selector and nonblank normalized text")
        return self


class HtmlMetadataSpec(BaseModel):
    """One visible region and an explicit flat text binding for each output field."""

    model_config = ConfigDict(extra="forbid", strict=True)

    region: str = Field(min_length=1, max_length=128)
    fields: dict[str, HtmlMetadataField] = Field(min_length=1, max_length=16)

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str) -> str:
        _selector(value)
        return value

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: dict[str, HtmlMetadataField]) -> dict[str, HtmlMetadataField]:
        if any(name == "id" or _FIELD.fullmatch(name) is None for name in value):
            raise ValueError("Use flat field names; id is reserved for generated output metadata")
        return value


@dataclass(slots=True)
class _Node:
    tag: str
    identity: str | None = None
    classes: tuple[str, ...] = ()
    hidden: bool = False
    spanning: bool = False
    row_header: bool = False
    children: list[_Node | str] = field(default_factory=list)


class _RenderedDOM(HTMLParser):
    """Parse bounded browser serialization, refusing malformed or oversized input."""

    def __init__(self, *, keep_hidden: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("")
        self.stack = [self.root]
        self.nodes = 0
        self.keep_hidden = keep_hidden

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES or len(self.stack) > MAX_DEPTH:
            raise HtmlMetadataError("layout_limit")
        values = dict(attrs)
        if len(values) != len(attrs):
            raise HtmlMetadataError("ambiguous_attributes")
        parent = self.stack[-1]
        # Chromium marks computed-hidden nodes on the frozen clone before serializing it.
        inline = "".join((values.get("style") or "").lower().split())
        hidden = (
            parent.hidden
            or tag in _HIDDEN
            or "hidden" in values
            or (values.get("aria-hidden") or "").lower() == "true"
            or any(
                part.rstrip(";").split("!", 1)[0] in {"display:none", "visibility:hidden"}
                for part in inline.split(";")
            )
        )
        node = _Node(
            tag,
            values.get("id"),
            tuple((values.get("class") or "").split()),
            hidden,
            "rowspan" in values or "colspan" in values,
            tag == "th" and (values.get("scope") or "").lower() == "row",
        )
        if self.keep_hidden or not hidden:
            parent.children.append(node)
        if not closed and tag not in _VOID:
            self.stack.append(node)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise HtmlMetadataError("unbalanced_layout")
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not self.stack[-1].hidden and data:
            self.stack[-1].children.append(data)


def _matching(root: _Node, selector: str) -> list[_Node]:
    tag, identity, css_class = _selector(selector)
    matches: list[_Node] = []
    todo = [root]
    while todo:
        node = todo.pop()
        if node.hidden:
            continue
        if (
            node.tag
            and (tag is None or node.tag == tag)
            and (identity is None or node.identity == identity)
            and (css_class is None or css_class in node.classes)
        ):
            matches.append(node)
            if len(matches) == 2:
                break  # Callers only distinguish none, unique, and ambiguous.
        todo.extend(child for child in reversed(node.children) if isinstance(child, _Node))
    return matches


def _text(node: _Node) -> str:
    pieces: list[str] = []
    todo = list(reversed(node.children))
    while todo:
        child = todo.pop()
        if isinstance(child, str):
            pieces.append(child)
        else:
            todo.extend(reversed(child.children))
    result = _space("".join(pieces))
    if not result or len(result) > MAX_TEXT_CHARS:
        raise HtmlMetadataError("blank_or_oversized_value")
    return result


def _elements(node: _Node) -> list[_Node]:
    result: list[_Node] = []
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                raise HtmlMetadataError("malformed_definition_list")
        else:
            result.append(child)
    return result


def _definitions(node: _Node) -> dict[str, str]:
    children = _elements(node)
    if children and all(child.tag == "div" for child in children):
        groups = [_elements(child) for child in children]
    else:
        groups = [children]
    result: dict[str, str] = {}
    for group in groups:
        if not group or len(group) % 2:
            raise HtmlMetadataError("malformed_definition_list")
        for term, value in zip(group[::2], group[1::2], strict=True):
            if term.tag != "dt" or value.tag != "dd":
                raise HtmlMetadataError("malformed_definition_list")
            name = _label(_text(term))
            if not name or name in result:
                raise HtmlMetadataError("ambiguous_definition_label")
            result[name] = _text(value)
    return result


def _parse_rendered_html(html: str, *, keep_hidden: bool = False) -> _Node:
    if len(html) > MAX_HTML_CHARS:
        raise HtmlMetadataError("layout_limit")
    parser = _RenderedDOM(keep_hidden=keep_hidden)
    parser.feed(html)
    parser.close()
    if len(parser.stack) != 1:
        raise HtmlMetadataError("unbalanced_layout")
    return parser.root


def literal_metadata(html: str, plan: HtmlMetadataSpec) -> dict[str, str | None]:
    """Return exact visible text (collapsed whitespace) or an explicitly allowed null."""
    regions = _matching(_parse_rendered_html(html), plan.region)
    if len(regions) != 1:
        raise HtmlMetadataError("record_region_not_unique")
    matches: dict[str, list[_Node]] = {}
    definitions: dict[str, dict[str, str]] = {}
    result: dict[str, str | None] = {}
    for name, binding in sorted(plan.fields.items()):
        selector = binding.selector
        if selector not in matches:
            matches[selector] = _matching(regions[0], selector)
        nodes = matches[selector]
        if len(nodes) > 1 or (binding.label is not None and not nodes):
            raise HtmlMetadataError("field_region_not_unique")
        if binding.label is None:
            value = _text(nodes[0]) if nodes else None
        else:
            if selector not in definitions:
                definitions[selector] = _definitions(nodes[0])
            value = definitions[selector].get(_label(binding.label))
        if value is None and binding.on_missing != "null":
            raise HtmlMetadataError("required_field_missing")
        result[name] = value
    return result
