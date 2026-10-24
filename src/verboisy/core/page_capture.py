# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Capture rendered page observations only within the current scope and byte limits."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from playwright.async_api import Page

from verboisy.evidence.models import Snapshot
from verboisy.utils.exceptions import NavigationError

if TYPE_CHECKING:
    from verboisy.core.research import ResearchRunner


CAPTURE_PAGE = """maxBytes => {
 const url=location.href, html=document.documentElement.outerHTML;
 if(new TextEncoder().encode(html).length > maxBytes) return {oversized:true};
 const copy=document.documentElement.cloneNode(true);
 const originals=[...document.documentElement.querySelectorAll('*')];
 const clones=[...copy.querySelectorAll('*')];
 originals.forEach((el,i)=>{ const s=getComputedStyle(el);
  if(s.display==='none'||s.visibility==='hidden'||el.hidden)
   clones[i].setAttribute('hidden',''); });
 return {url,html,visible_html:copy.outerHTML,oversized:false};
}"""


async def capture_rendered_page(
    runner: ResearchRunner,
    page: Page,
    canonicalize: Callable[[str], str | None],
    make_snapshot: Callable[..., Snapshot],
    capture_script: str,
) -> tuple[Snapshot, str, str, str]:
    """Check the rendered destination and size before creating source evidence."""
    await asyncio.sleep(runner.task.settle_ms / 1000)
    observation = await page.evaluate(capture_script, runner.config.max_page_bytes)
    if observation["oversized"]:
        raise NavigationError("Page exceeds configured size limit")
    url = canonicalize(observation["url"])
    if url is None or not runner.in_scope(url):
        raise NavigationError("Redirect left the declared crawl scope")
    html, visible_html = observation["html"], observation["visible_html"]
    if len(html.encode()) > runner.config.max_page_bytes:
        raise NavigationError("Page exceeds configured size limit")
    column_tables = getattr(runner.task, "column_tables", [])
    if column_tables:
        try:
            captured = make_snapshot(
                visible_html,
                url,
                runner.config.max_snapshot_chars,
                column_tables=column_tables,
            )
        except ValueError as error:
            raise NavigationError("Declared column table rejected: " + str(error)) from error
    else:
        captured = make_snapshot(visible_html, url, runner.config.max_snapshot_chars)
    drain = getattr(runner.browser, "drain_policy_failures", None)
    if callable(drain):
        for notice in drain():
            runner.store.event(
                runner.rid,
                "coverage_gap",
                {"snapshot_id": captured.id, "reason": notice["reason"], "count": notice["count"]},
            )
    return captured, url, html, visible_html
