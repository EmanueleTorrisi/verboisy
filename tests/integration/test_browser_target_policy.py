# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real primary/secondary-target request counters; missing Chromium is a gate failure."""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from verboisy.browser.context import BrowserManager
from verboisy.utils.config import Settings

pytestmark = pytest.mark.browser


@pytest.mark.parametrize(
    "target", ["popup", "anchor", "blank_fetch", "frame", "worker", "websocket", "redirect"]
)
@pytest.mark.parametrize("scoped", [True, False])
async def test_forbidden_target_has_zero_hits(target, scoped):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            hits.append((self.headers.get("Host"), self.path))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{self.server.server_port}/forbidden"
                )
                self.end_headers()
            else:
                body = b"<html><body>primary</body></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    manager = BrowserManager(
        Settings(
            _env_file=None,
            allow_private_network=True,
            allowed_domains=["localhost"],
            browser_auto_install=False,
            browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
        )
    )
    origin = f"http://localhost:{server.server_port}"
    forbidden = f"http://127.0.0.1:{server.server_port}/forbidden"
    if scoped:
        manager.navigation_scope = lambda url: url.startswith(origin)
    try:
        await manager.navigate_to(origin + "/primary")
        page = await manager.get_page()
        scripts = {
            "popup": "url => window.open(url)",
            "anchor": (
                'url => {const a=document.createElement("a");a.href=url;'
                'a.target="_blank";document.body.append(a);a.click()}'
            ),
            "blank_fetch": 'url => {const p=window.open("about:blank");p.fetch(url).catch(()=>{})}',
            "frame": (
                'url => {const f=document.createElement("iframe");f.src=url;'
                "document.body.append(f)}"
            ),
            "worker": "url => {try {new Worker(url)} catch(e) {}}",
            "websocket": 'url => {new WebSocket(url.replace("http:","ws:"))}',
            "redirect": "url => {location.href=url}",
        }
        await page.evaluate(
            scripts[target], origin + "/redirect" if target == "redirect" else forbidden
        )
        await asyncio.sleep(0.2)
        assert not any(host.startswith("127.0.0.1") for host, _ in hits)
        assert ("localhost:" + str(server.server_port), "/primary") in hits
        if target not in {"worker", "websocket"}:
            assert manager.drain_policy_failures()
    finally:
        await manager.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
