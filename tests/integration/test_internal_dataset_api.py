# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real HTTP acquisition keeps internal API credentials bound to their origin."""

import json
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest
from verboisy import arun
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings


@pytest.fixture
def endpoints():
    seen = []
    destinations = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):  # noqa: N802 - HTTP server interface
            seen.append(
                (
                    self.server.server_port,
                    self.path,
                    self.headers.get("Authorization"),
                    self.headers.get("Cookie"),
                )
            )
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", destinations["other"] + "/rows")
                self.send_header("Set-Cookie", "session=PRIVATE; Path=/")
                self.end_headers()
                return
            body = b'[{"name":"Alice"}]'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    bases = [f"http://127.0.0.1:{server.server_port}" for server in servers]
    destinations["other"] = bases[1]
    try:
        yield bases, seen
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


@pytest.mark.parametrize("redirect", [False, True])
async def test_internal_api_acquisition_and_port_isolation(tmp_path, endpoints, redirect):
    bases, seen = endpoints
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "run.db"),
        allow_private_network=True,
        allowed_domains=["127.0.0.1"],
        search_provider="disabled",
        dataset_http_headers={bases[0]: {"Authorization": "Bearer PRIVATE"}},
    )
    with (
        patch(
            "verboisy.llm.client.LLMClient.complete_json",
            new=AsyncMock(side_effect=AssertionError("model")),
        ),
        patch(
            "verboisy.browser.context.BrowserManager.start",
            new=AsyncMock(side_effect=AssertionError("browser")),
        ),
        patch("verboisy.api.web_search", new=AsyncMock(side_effect=AssertionError("search"))),
    ):
        result = await arun(
            goal="Names",
            schema=["name"],
            dataset_sources=[
                {"url": bases[0] + ("/redirect" if redirect else "/rows"), "format": "json"}
            ],
            task={"target_records": 1},
            config=config,
        )
    assert result.status == "COMPLETED"
    assert seen[0][2] == "Bearer PRIVATE"
    if redirect:
        assert len(seen) == 2 and seen[1][2:] == (None, None)
    with closing(ResearchStore(config.sqlite_db_path, read_only=True)) as store:
        assert "PRIVATE" not in json.dumps(dict(store.load(result.run_id)))
        assert "PRIVATE" not in json.dumps(store.events(result.run_id))
        assert "PRIVATE" not in str(store.dataset_assets(result.run_id))
