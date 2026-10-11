# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""HTTP transport that connects only to addresses validated for that connection."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import httpcore
import httpx

from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError

CORE_ERRORS = (
    httpcore.TimeoutException,
    httpcore.NetworkError,
    httpcore.ProtocolError,
    httpcore.UnsupportedProtocol,
    httpcore.ProxyError,
)


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except CORE_ERRORS as error:
        raise httpx.TransportError(type(error).__name__) from None


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self, config: Settings, delegate: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self.config = config
        self.delegate = delegate if delegate is not None else httpcore.AnyIOBackend()

    async def _addresses(self, host: str, port: int) -> list[str]:
        normalized = host.rstrip(".").lower()
        if self.config.allowed_domains and normalized not in {
            domain.rstrip(".").lower().encode("idna").decode("ascii")
            for domain in self.config.allowed_domains
        }:
            raise NavigationError("Connection host is outside ALLOWED_DOMAINS")
        try:
            addresses = [ipaddress.ip_address(normalized)]
        except ValueError:
            try:
                records = await asyncio.get_running_loop().getaddrinfo(
                    normalized, port, type=socket.SOCK_STREAM
                )
                addresses = [ipaddress.ip_address(record[4][0]) for record in records]
            except (OSError, ValueError):
                raise NavigationError("Unable to resolve connection host") from None
        if not addresses or (
            not self.config.allow_private_network
            and any(not address.is_global for address in addresses)
        ):
            raise NavigationError("Non-public connection address is blocked")
        return list(dict.fromkeys(str(address) for address in addresses))

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            async with asyncio.timeout(timeout):
                addresses = await self._addresses(host, port)
                last_error: Exception | None = None
                # Dial the validated literal address, preventing a second DNS lookup
                # from changing the destination between policy checking and connection.
                for address in addresses:
                    try:
                        return await self.delegate.connect_tcp(
                            address,
                            port,
                            timeout=timeout,
                            local_address=local_address,
                            socket_options=socket_options,
                        )
                    except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                        last_error = error
                assert last_error is not None
                raise last_error
        except TimeoutError:
            raise httpcore.ConnectTimeout("Connection deadline exceeded") from None

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self.response = response

    async def __aiter__(self) -> AsyncIterator[bytes]:
        with _translate_errors():
            async for chunk in self.response.aiter_stream():
                yield chunk

    async def aclose(self) -> None:
        with _translate_errors():
            await self.response.aclose()


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        config: Settings,
        *,
        ssl_context: ssl.SSLContext | None = None,
        delegate: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        context = ssl_context if ssl_context is not None else ssl.create_default_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("Dataset TLS requires certificate and hostname verification")
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=context,
            network_backend=PinnedBackend(config, delegate),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with _translate_errors():
            response = await self.pool.handle_async_request(core_request)
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        with _translate_errors():
            await self.pool.aclose()
