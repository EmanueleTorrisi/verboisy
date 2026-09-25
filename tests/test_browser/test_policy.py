"""Tests for browser navigation security policies."""

import asyncio
import socket
from unittest.mock import AsyncMock

import pytest
from verboisy.browser.policy import validate_url
from verboisy.utils.exceptions import NavigationError


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path\\unsafe",
        "https://example.com/path\nunsafe",
        "https://example.com/path\x00unsafe",
    ],
)
async def test_rejects_unsafe_url_characters(config, url):
    """Reject URLs containing backslashes or control characters."""
    config.allowed_domains = []

    with pytest.raises(
        NavigationError,
        match="URL contains unsafe characters",
    ):
        await validate_url(url, config)


async def test_dns_resolution_failure(config, monkeypatch):
    """Reject destinations when DNS resolution fails."""
    config.allowed_domains = []
    config.allow_private_network = False

    mock_getaddrinfo = AsyncMock(
        side_effect=socket.gaierror(
            socket.EAI_NONAME,
            "Simulated DNS resolution failure",
        )
    )

    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        mock_getaddrinfo,
    )

    with pytest.raises(
        NavigationError,
        match="Unable to resolve destination host",
    ):
        await validate_url(
            "https://example.com",
            config,
        )

    mock_getaddrinfo.assert_awaited_once()
