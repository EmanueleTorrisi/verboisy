# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded DOM evidence and actual links, with explicit truncation."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, Tag

from verboisy.evidence.models import Snapshot, Source


def canonical_url(value: str, base: str = "") -> str | None:
    try:
        url = urlsplit(urljoin(base, value))
        if url.scheme.lower() not in ("http", "https") or not url.hostname:
            return None
        if url.username or url.password or any(ord(c) < 33 for c in value) or "\\" in value:
            return None
        host = url.hostname.encode("idna").decode().lower()
        if ":" in host:
            host = f"[{host}]"
        port = url.port
        if port and (url.scheme.lower(), port) not in (("http", 80), ("https", 443)):
            host += f":{port}"
        fragment = url.fragment if url.fragment.startswith(("/", "!")) else ""
        return urlunsplit((url.scheme.lower(), host, url.path or "/", url.query, fragment))
    except (ValueError, UnicodeError):
        return None


def whitespace(text: str) -> str:
    return " ".join(text.split())


def snapshot(html: str, url: str, max_chars: int = 120000) -> Snapshot:
    soup = BeautifulSoup(html, "html.parser")
    for node in list(soup.select("script, style, noscript, svg, template, iframe, head")):
        node.decompose()
    for node in list(soup.select('[hidden], [aria-hidden="true"]')):
        if node.parent is not None:
            node.decompose()
    for node in list(soup.select("[style]")):
        style = str(node.get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            node.decompose()
    container = soup.body or soup
    entity_selector = "article, li, [itemscope], [data-record]"
    entity_ids = {id(n) for n in container.select(entity_selector)}
    scope_nodes = []

    for node in container.select("tr, article, li, [itemscope], [data-record]"):
        # Header-only rows describe the table rather than an entity.
        if node.name == "tr" and node.find("td", recursive=False) is None:
            continue

        # A table row is an entity boundary only when it is not already inside
        # a stronger entity container. Product-detail tables commonly use rows
        # for attributes of the surrounding article, not separate entities.
        if node.name == "tr" and any(id(parent) in entity_ids for parent in node.parents):
            continue

        scope_nodes.append(node)

    scopes = {id(node): f"s{i}" for i, node in enumerate(scope_nodes)}

    def scope(node: Tag) -> str:
        return next((scopes[id(p)] for p in [node, *node.parents] if id(p) in scopes), "page")

    sources: list[Source] = []
    used = 0
    truncated = False
    for node in [container, *container.find_all(True)]:
        if node.name == "a" and node.get("href"):
            href = canonical_url(str(node["href"]), url)
            if href is None:
                continue
            item = Source(
                id=f"e{len(sources)}",
                kind="link",
                text=whitespace(node.get_text(" ", strip=True)),
                href=href,
                scope=scope(node),
            )
        else:
            text = whitespace(
                " ".join(
                    str(c)
                    for c in node.children
                    if isinstance(c, str) and not isinstance(c, Comment)
                )
            )
            if not text:
                continue
            item = Source(id=f"e{len(sources)}", kind="text", text=text, scope=scope(node))
        size = len(item.model_dump_json())
        if used + size > max_chars:
            truncated = True
            continue
        used += size
        sources.append(item)
    digest = hashlib.sha256(html.encode()).hexdigest()
    stamp = datetime.now(UTC).isoformat()
    sid = hashlib.sha256((url + stamp + digest).encode()).hexdigest()
    return Snapshot(
        id=sid, url=url, fetched_at=stamp, content_hash=digest, sources=sources, truncated=truncated
    )


def chunks(page: Snapshot, limit: int) -> list[list[Source]]:
    ("Supply all admitted evidence in complete JSON objects, without pr" "efix truncation.")
    groups: dict[str, list[Source]] = {}
    for source in page.sources:
        groups.setdefault(source.scope, []).append(source)
    batches: list[list[Source]] = []
    batch: list[Source] = []
    size = 0
    for sources in groups.values():
        group_size = sum(len(s.model_dump_json()) for s in sources)
        # Prefer keeping a complete entity together when it fits in a single request.
        if batch and size + group_size > limit:
            batches.append(batch)
            batch, size = [], 0
        for source in sources:
            item_size = len(source.model_dump_json())
            if item_size > limit:
                raise ValueError("evidence_block_exceeds_model_budget")
            if batch and size + item_size > limit:
                batches.append(batch)
                batch, size = [], 0
            batch.append(source)
            size += item_size
    if batch:
        batches.append(batch)
    return batches
