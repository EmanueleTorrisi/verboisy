# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""
DOM cleaning and parsing utility for optimizing LLM context windows.
"""

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Comment, Tag

from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class DOMParser:
    ("Cleans raw HTML into a streamlined, LLM-friendly textual/structur" "al representation.")

    @staticmethod
    def clean_html(html_content: str) -> str:
        """
        Remove unnecessary tags (scripts, styles, SVGs, comments) from HTML
        and return a clean, compact HTML string.

        Args:
            html_content: Raw HTML string from page.content()

        Returns:
            str: Cleaned HTML string.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Resource links and metadata can consume the entire bounded model input.
        # Keep the title and actual <a href> evidence, but remove non-content tags.
        for tag in soup(
            ["script", "style", "svg", "noscript", "iframe", "footer", "header", "link", "meta"]
        ):
            tag.decompose()

        # Remove comments
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        for comment in comments:
            comment.extract()

        # Strip attributes that bloat tokens (e.g. inline styles, massive classes)
        for tag in soup.find_all(True):
            allowed_attrs = {}
            for attr in [
                "href",
                "alt",
                "title",
                "id",
                "name",
                "class",
                "type",
                "role",
                "aria-label",
                "placeholder",
                "for",
                "value",
                "checked",
                "selected",
                "disabled",
                "aria-checked",
                "aria-expanded",
                "aria-disabled",
            ]:
                if tag.has_attr(attr):
                    allowed_attrs[attr] = tag[attr]
            tag.attrs = allowed_attrs

        cleaned = str(soup)
        # Collapse multiple newlines/spaces
        cleaned = "\n".join([line.strip() for line in cleaned.splitlines() if line.strip()])
        return cleaned

    @staticmethod
    def extract_interactive_elements(html_content: str) -> str:
        ("Bounded control descriptions, associated labels and selectors fro" "m the observed DOM.")
        soup = BeautifulSoup(html_content, "html.parser")
        elements = []
        controls = soup.select(
            "a[href], button, input, select, textarea, label, summary, "
            '[role="button"], [role="checkbox"], [role="radio"], [role="combobox"]'
        )
        # Controls precede long company-link lists, so filters survive truncation.
        controls.sort(key=lambda el: el.name == "a")
        for el in controls[:100]:
            if el.get("type") in ("hidden", "password") or el.has_attr("hidden"):
                continue
            label = soup.find("label", attrs={"for": str(el.get("id"))}) if el.get("id") else None
            if label is None:
                label = el.find_parent("label")
            text = el.get("aria-label") or (
                label.get_text(" ", strip=True) if label else el.get_text(" ", strip=True)
            )
            attributes = {
                name: el.attrs[name]
                for name in (
                    "href",
                    "type",
                    "name",
                    "placeholder",
                    "role",
                    "aria-expanded",
                    "aria-checked",
                    "aria-disabled",
                    "checked",
                    "disabled",
                    "value",
                )
                if name in el.attrs
            }
            element: dict[str, Any] = {
                "tag": el.name,
                "selector": DOMParser._selector(el, soup),
                "label": str(text)[:160],
                "html_attributes": attributes,
            }
            if el.name == "select":
                element["options"] = [
                    {
                        "value": option.get("value", option.get_text()),
                        "label": option.get_text(strip=True),
                    }
                    for option in el.find_all("option")[:50]
                ]
            elements.append(element)
        return json.dumps(elements, ensure_ascii=False)

    @staticmethod
    def _selector(el: Tag, soup: BeautifulSoup) -> str:
        identifier = str(el.get("id", ""))
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", identifier)
            and len(soup.find_all(id=identifier)) == 1
        ):
            return "#" + identifier
        parts = []
        for node in [el, *el.parents]:
            if node.name == "[document]":
                continue
            index = 1 + len(node.find_previous_siblings(node.name))
            parts.append(f"{node.name}:nth-of-type({index})")
        return " > ".join(reversed(parts))


def clean_html(html_content: str) -> str:
    """Clean HTML using DOMParser."""
    return DOMParser.clean_html(html_content)
