# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real Chromium source-scope redirects; loopback fixture and no model requests."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest
from verboisy.core.research import ResearchRunner
from verboisy.evidence.models import TaskSpec
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError

pytestmark = pytest.mark.browser


@pytest.mark.parametrize(
    "case,status",
    [
        ("outside_host", 302),
        ("avoided_host", 302),
        ("excluded_path", 302),
        ("second_hop", 302),
        ("allowed", 302),
        ("allowed", 301),
        ("allowed", 303),
        ("allowed", 307),
        ("allowed", 308),
    ],
)
async def test_redirect_scope_before_destination_fetch(tmp_path, case, status):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            requests.append(self.path)
            if self.path == "/safe/start" or self.path == "/safe/hop":
                host = (
                    "127.0.0.1"
                    if case in {"outside_host", "avoided_host", "second_hop"}
                    else "localhost"
                )
                path = "/safe/blocked" if case == "excluded_path" else "/safe/end"
                if case == "second_hop" and self.path == "/safe/start":
                    host, path = "localhost", "/safe/hop"
                self.send_response(status)
                self.send_header("Location", f"http://{host}:{self.server.server_port}{path}")
                self.end_headers()
            else:
                body = b"<html><body><img src='/asset.png'>Fixture</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    store = ResearchStore(str(tmp_path / "run.db"))
    task = TaskSpec(
        allowed_hosts=[] if case == "avoided_host" else ["localhost"],
        avoided_hosts=["127.0.0.1"] if case in {"avoided_host", "second_hop"} else [],
        include_paths=["/safe/*"],
        exclude_paths=["/safe/blocked"],
        settle_ms=0,
    )
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    rid = store.create("Redirect fixture", schema, task, None)
    runner = ResearchRunner(
        store,
        rid,
        Settings(
            _env_file=None,
            allow_private_network=True,
            search_provider="disabled",
            browser_auto_install=False,
            browser_sandbox=os.environ.get("TEST_BROWSER_SANDBOX", "true") == "true",
        ),
    )
    try:
        with patch(
            "verboisy.llm.client.LLMClient.complete_json",
            AsyncMock(side_effect=AssertionError("Unexpected model")),
        ) as model:
            start = f"http://localhost:{server.server_port}/safe/start"
            if case == "allowed":
                await runner.browser.navigate_to(start)
                page = await runner.browser.get_page()
                assert page.url == f"http://localhost:{server.server_port}/safe/end"
                await page.wait_for_load_state("load")
                assert "/safe/end" in requests
                assert "/asset.png" in requests
            else:
                store.queue(rid, start, 0, None)
                with pytest.raises(NavigationError):
                    await runner.process(store.next_page(rid))
                assert "/safe/end" not in requests
                assert "/safe/blocked" not in requests
                if case == "second_hop":
                    assert "/safe/hop" in requests
                assert store.records(rid) == []
            assert "/safe/start" in requests
            model.assert_not_awaited()
    finally:
        await runner.browser.close()
        store.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
