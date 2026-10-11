# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real loopback HTTP dataset acquisition, with no public network or model calls."""

import gzip
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from verboisy.extractor.dataset import DatasetParseError
from verboisy.extractor.download import DatasetDownloadError, download_dataset
from verboisy.utils.config import Settings

from tests.test_extractor.test_dataset_parser import csv_bytes


async def test_seven_real_http_fixtures():
    content = csv_bytes()
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler interface
            seen.append(self.path)
            status, body = 200, content
            headers = {"Content-Type": "text/csv; charset=utf-8"}
            if self.path == "/redirect.csv":
                status, body = 302, b""
                headers["Location"] = "/people.csv"
            elif self.path == "/outside.csv":
                status, body = 302, b""
                headers["Location"] = f"http://localhost:{self.server.server_port}/forbidden.csv"
            elif self.path == "/misleading.csv":
                body = b"<!doctype html><html>Access denied</html>"
            elif self.path == "/compressed.csv":
                body = gzip.compress(content, mtime=0)
                headers["Content-Encoding"] = "gzip"
            elif self.path == "/unsafe-name.csv":
                headers["Content-Disposition"] = 'attachment; filename="../../outside.csv"'
            elif self.path == "/large.csv":
                body = b"person,note\nA," + b"x" * 4096 + b"\n"
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    config = Settings(_env_file=None, allow_private_network=True, allowed_domains=["127.0.0.1"])

    def permits(url):
        parsed = urlsplit(url)
        return parsed.hostname == "127.0.0.1" and parsed.port == server.server_port

    async def fetch(path):
        return await download_dataset(
            base + path, config, dataset_format="csv", permits=permits, max_bytes=1024
        )

    try:
        first = await fetch("/people.csv")
        assert first.dataset.original_bytes == content
        assert first.dataset.rows[0].values["person"] == "Anaïs"
        assert first.dataset.rows[1].values["person"] == "李雷"
        redirected = await fetch("/redirect.csv")
        assert redirected.dataset.sha256 == first.dataset.sha256
        assert redirected.final_url == base + "/people.csv"
        with pytest.raises(DatasetDownloadError, match="scope"):
            await fetch("/outside.csv")
        with pytest.raises(DatasetParseError, match="Markup"):
            await fetch("/misleading.csv")
        with pytest.raises(DatasetDownloadError, match="Compressed"):
            await fetch("/compressed.csv")
        named = await fetch("/unsafe-name.csv")
        assert "../" in named.remote_disposition
        assert named.dataset.sha256 == first.dataset.sha256
        with pytest.raises(DatasetDownloadError, match="byte limit"):
            await fetch("/large.csv")
        assert "/forbidden.csv" not in seen
        assert seen.count("/people.csv") == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
