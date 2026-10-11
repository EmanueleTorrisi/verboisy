# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Connections use validated literals while the original HTTP/TLS origin is retained."""

import asyncio
import ipaddress
import socket
import ssl
from unittest.mock import AsyncMock

import httpcore
import httpx
import pytest
from verboisy.extractor.download import DatasetDownloadError, download_dataset
from verboisy.extractor.transport import PinnedBackend, PinnedTransport, _ResponseStream
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError


class Stream(httpcore.AsyncNetworkStream):
    def __init__(self, error=None):
        self.data = (
            b"HTTP/1.1 200 OK\r\nContent-Type: text/csv\r\n"
            b"Content-Length: 13\r\nConnection: close\r\n\r\nperson\nAnais\n"
        )
        self.writes = []
        self.tls_names = []
        self.closed = False
        self.error = error

    async def read(self, max_bytes, timeout=None):  # noqa: ARG002 - network stream interface
        if self.error:
            raise self.error
        value, self.data = self.data[:max_bytes], self.data[max_bytes:]
        return value

    async def write(self, buffer, timeout=None):  # noqa: ARG002 - network stream interface
        self.writes.append(buffer)

    async def aclose(self):
        self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):  # noqa: ARG002 - network stream interface
        assert ssl_context.check_hostname
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        self.tls_names.append(server_hostname)
        return self

    def get_extra_info(self, info):  # noqa: ARG002 - network stream interface
        return None


def records(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
        for address in addresses
    ]


def config(**kwargs):
    return Settings(_env_file=None, allow_private_network=False, **kwargs)


async def test_rebinding_cannot_change_validated_address(monkeypatch):
    dns = AsyncMock(side_effect=[records("8.8.8.8"), records("127.0.0.1")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    stream = Stream()
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(return_value=stream)
    backend = PinnedBackend(config(), delegate)
    assert await backend.connect_tcp("assets.example.test", 443) is stream
    delegate.connect_tcp.assert_awaited_once_with(
        "8.8.8.8", 443, timeout=None, local_address=None, socket_options=None
    )
    assert dns.await_count == 1
    assert ipaddress.ip_address(delegate.connect_tcp.call_args.args[0]).is_global


async def test_dns_flip_between_precheck_and_connection_is_blocked(monkeypatch):
    dns = AsyncMock(side_effect=[records("8.8.8.8"), records("127.0.0.1")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(side_effect=AssertionError("Unexpected socket"))
    real = PinnedTransport
    monkeypatch.setattr(
        "verboisy.extractor.download.PinnedTransport", lambda cfg: real(cfg, delegate=delegate)
    )
    with pytest.raises(DatasetDownloadError, match="network policy"):
        await download_dataset(
            "https://assets.example.test/data.csv",
            config(),
            dataset_format="csv",
            permits=lambda _url: True,
        )
    assert dns.await_count == 2
    delegate.connect_tcp.assert_not_awaited()


@pytest.mark.parametrize(
    "answers",
    [
        records("127.0.0.1"),
        records("::1"),
        records("::ffff:127.0.0.1"),
        records("8.8.8.8", "10.0.0.1"),
        [],
    ],
)
async def test_all_answers_must_be_public(monkeypatch, answers):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers))
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock()
    with pytest.raises(NavigationError):
        await PinnedBackend(config(), delegate).connect_tcp("assets.example.test", 443)
    delegate.connect_tcp.assert_not_awaited()


@pytest.mark.parametrize("answer", [OSError("secret"), records("not-an-address")])
async def test_resolution_failures_are_redacted(monkeypatch, answer):
    resolver = (
        AsyncMock(side_effect=answer)
        if isinstance(answer, Exception)
        else AsyncMock(return_value=answer)
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(NavigationError, match="Unable to resolve") as caught:
        await PinnedBackend(config()).connect_tcp("assets.example.test", 443)
    assert "secret" not in str(caught.value)


async def test_literal_address_needs_no_dns(monkeypatch):
    resolver = AsyncMock(side_effect=AssertionError("Unexpected DNS"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    stream = Stream()
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(return_value=stream)
    await PinnedBackend(config(), delegate).connect_tcp("2606:4700:4700::1111", 443)
    resolver.assert_not_awaited()


async def test_allowlist_is_enforced_before_dns(monkeypatch):
    resolver = AsyncMock(side_effect=AssertionError("Unexpected DNS"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(NavigationError, match="ALLOWED_DOMAINS"):
        await PinnedBackend(config(allowed_domains=["allowed.test"])).connect_tcp(
            "outside.test", 443
        )
    resolver.assert_not_awaited()


async def test_verified_address_fallback_no_new_dns(monkeypatch):
    resolver = AsyncMock(return_value=records("8.8.8.8", "1.1.1.1", "8.8.8.8"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    stream = Stream()
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(side_effect=[httpcore.ConnectError("fixture"), stream])
    result = await PinnedBackend(config(), delegate).connect_tcp(
        "assets.example.test",
        443,
        local_address="0.0.0.0",
        socket_options=[(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)],
    )
    assert result is stream
    assert [call.args[0] for call in delegate.connect_tcp.call_args_list] == ["8.8.8.8", "1.1.1.1"]
    assert resolver.await_count == 1


async def test_all_connections_failed(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=records("8.8.8.8"))
    )
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(side_effect=httpcore.ConnectTimeout("fixture"))
    with pytest.raises(httpcore.ConnectTimeout):
        await PinnedBackend(config(), delegate).connect_tcp("assets.example.test", 443)


async def test_resolve_timeout_and_cancellation(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", slow)
    with pytest.raises(httpcore.ConnectTimeout):
        await PinnedBackend(config()).connect_tcp("assets.example.test", 443, timeout=0.001)
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=asyncio.CancelledError())
    )
    with pytest.raises(asyncio.CancelledError):
        await PinnedBackend(config()).connect_tcp("assets.example.test", 443)
    await PinnedBackend(config()).sleep(0)


async def test_original_host_and_tls_name_are_retained(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=records("8.8.8.8"))
    )
    stream = Stream()
    delegate = httpcore.AsyncMockBackend([])
    delegate.connect_tcp = AsyncMock(return_value=stream)
    async with httpx.AsyncClient(
        transport=PinnedTransport(config(), delegate=delegate), trust_env=False
    ) as client:
        response = await client.get("https://assets.example.test:8443/data.csv")
        assert response.content == b"person\nAnais\n"
    assert stream.tls_names == ["assets.example.test"]
    assert b"Host: assets.example.test:8443\r\n" in b"".join(stream.writes)
    assert stream.closed


@pytest.mark.parametrize("mode", ["hostname", "certificate"])
def test_tls_verification_cannot_be_disabled(mode):
    context = ssl.create_default_context()
    if mode == "hostname":
        context.check_hostname = False
    else:
        context.verify_mode = ssl.CERT_OPTIONAL
    with pytest.raises(ValueError, match="verification"):
        PinnedTransport(config(), ssl_context=context)


async def test_pool_error_translation():
    transport = PinnedTransport(config())
    transport.pool.handle_async_request = AsyncMock(side_effect=httpcore.ConnectError("secret"))
    try:
        with pytest.raises(httpx.TransportError) as caught:
            await transport.handle_async_request(
                httpx.Request("GET", "https://assets.example.test")
            )
        assert str(caught.value) == "ConnectError"
    finally:
        await transport.aclose()


async def test_response_read_and_close_errors_are_translated():
    class BadStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise httpcore.ReadError("secret")

        async def aclose(self):
            raise httpcore.WriteError("secret")

    response = httpcore.Response(200, content=BadStream())
    adapter = _ResponseStream(response)
    with pytest.raises(httpx.TransportError, match="ReadError"):
        await adapter.__aiter__().__anext__()
    with pytest.raises(httpx.TransportError, match="WriteError"):
        await adapter.aclose()
