# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Best-effort network boundary for browser-driven research."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from verboisy.utils.config import Settings
from verboisy.utils.exceptions import NavigationError


async def validate_url(url: str, config: Settings) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise NavigationError("Malformed navigation URL") from None
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        raise NavigationError("Only HTTP(S) URLs without embedded credentials are allowed")
    if any(ord(c) < 32 for c in url) or "\\" in url:
        raise NavigationError("URL contains unsafe characters")
    host = host.rstrip(".").lower()
    if config.allowed_domains and host not in {
        h.rstrip(".").lower() for h in config.allowed_domains
    }:
        raise NavigationError("Destination is outside ALLOWED_DOMAINS")
    if config.allow_private_network:
        return
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
            addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        except OSError:
            raise NavigationError("Unable to resolve destination host") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise NavigationError("Private, local, and non-public network destinations are blocked")
