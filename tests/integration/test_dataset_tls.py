# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Real TLS validates the original DNS hostname over a pinned loopback connection."""

import asyncio
import socket
import ssl
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock

import pytest
from verboisy.extractor.download import DatasetDownloadError, download_dataset
from verboisy.extractor.transport import PinnedTransport
from verboisy.utils.config import Settings

from tests.test_extractor.tls_fixture import CERTIFICATE, PRIVATE_KEY


async def test_real_tls_hostname_validation_over_pinned_ip(tmp_path, monkeypatch):
    cert = tmp_path / "certificate.pem"
    key = tmp_path / "test-key.pem"
    cert.write_text(CERTIFICATE)
    key.write_text(PRIVATE_KEY)
    hosts = []
    tls_names = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802 - HTTP server interface
            hosts.append(self.headers["Host"])
            body = b"person\nAnais\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server_context.set_servername_callback(lambda _socket, name, _context: tls_names.append(name))
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cadata=CERTIFICATE)
    config = Settings(
        _env_file=None,
        allow_private_network=True,
        allowed_domains=["assets.example.test", "wrong.example.test"],
    )
    dns = AsyncMock(
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", server.server_port))
        ]
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    monkeypatch.setattr(
        "verboisy.extractor.download.PinnedTransport",
        lambda cfg: PinnedTransport(cfg, ssl_context=client_context),
    )
    try:
        result = await download_dataset(
            f"https://assets.example.test:{server.server_port}/data.csv",
            config,
            dataset_format="csv",
            permits=lambda _url: True,
        )
        assert result.dataset.rows[0].values == {"person": "Anais"}
        assert hosts == [f"assets.example.test:{server.server_port}"]
        assert tls_names == ["assets.example.test"]
        assert dns.await_count == 1
        with pytest.raises(DatasetDownloadError):
            await download_dataset(
                f"https://wrong.example.test:{server.server_port}/data.csv",
                config,
                dataset_format="csv",
                permits=lambda _url: True,
            )
        assert len(hosts) == 1  # The mismatched certificate blocks before HTTP GET.
        assert tls_names == ["assets.example.test", "wrong.example.test"]
        assert dns.await_count == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
