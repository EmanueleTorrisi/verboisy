# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real loopback acquisition persists after the HTTP source is shut down."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
from verboisy.evidence.models import TaskSpec
from verboisy.extractor.download import download_dataset
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings


@pytest.mark.parametrize(
    "fmt,content",
    [
        ("csv", 'name,note\r\nAnaïs,"first\nsecond"\r\n李雷,=1+1\r\n'.encode()),
        ("json", '[{"name":"Anaïs","age":31},{"name":"李雷","age":null}]'.encode()),
        ("jsonl", '\n{"name":"Anaïs"}\n\n{"name":"李雷"}\n'.encode()),
    ],
)
async def test_real_download_survives_offline_resume(tmp_path, fmt, content):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802 - standard server interface
            seen.append(self.path)
            self.send_response(302 if self.path == "/start" else 200)
            body = b"" if self.path == "/start" else content
            if self.path == "/start":
                self.send_header("Location", "/data")
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="../../escape"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    config = Settings(_env_file=None, allow_private_network=True, allowed_domains=["127.0.0.1"])
    database = tmp_path / "resume.db"
    try:
        downloaded = await download_dataset(
            base + "/start",
            config,
            dataset_format=fmt,
            permits=lambda url: url in {base + "/start", base + "/data"},
        )
        store = ResearchStore(str(database))
        try:
            rid = store.create("Capture source", {}, TaskSpec(), None)
            asset_id = store.save_dataset_asset(rid, downloaded)
            saved = store.load_dataset_asset(rid, asset_id)
            before = store.events(rid)
            assert store.records(rid) == []
        finally:
            store.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    with (
        patch("httpx.AsyncClient", side_effect=AssertionError("unexpected download")),
        patch("verboisy.llm.client.LLMClient.complete_json", side_effect=AssertionError("model")),
    ):
        reopened = ResearchStore(str(database))
        try:
            for _ in range(2):
                assert reopened.load_dataset_asset(rid, asset_id) == saved
                assert reopened.dataset_assets(rid) == [saved]
                assert reopened.save_dataset_asset(rid, downloaded) == asset_id
                assert reopened.events(rid) == before
            assert saved.download.dataset.original_bytes == content
            assert saved.download.final_url == base + "/data"
            assert saved.download.redirect_chain == (base + "/start", base + "/data")
            assert reopened.load(rid)["tokens"] == reopened.load(rid)["reserved"] == 0
        finally:
            reopened.close()
    assert seen == ["/start", "/data"]
    assert not (tmp_path.parent / "escape").exists()
