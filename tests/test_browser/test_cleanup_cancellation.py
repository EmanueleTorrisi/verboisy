# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cancellation must propagate after attempting the remaining browser cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from verboisy.browser.context import BrowserManager

RESOURCES = (
    ("_request_session", "detach"),
    ("_page", "close"),
    ("_context", "close"),
    ("_browser", "close"),
    ("_playwright", "stop"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", range(5))
async def test_cleanup_cancellation_attempts_all_resources_and_preserves_first_error(cancel_at):
    manager = BrowserManager()
    cancellation = asyncio.CancelledError("First cancellation")
    operations = []
    for index, (attribute, method) in enumerate(RESOURCES):
        operation = AsyncMock()
        if index == cancel_at:
            operation.side_effect = cancellation
        elif index > cancel_at:
            operation.side_effect = asyncio.CancelledError("Later cancellation")
        setattr(manager, attribute, SimpleNamespace(**{method: operation}))
        operations.append(operation)

    with pytest.raises(asyncio.CancelledError) as caught:
        await manager.close()
    assert caught.value is cancellation
    for (attribute, _), operation in zip(RESOURCES, operations, strict=True):
        operation.assert_awaited_once()
        assert getattr(manager, attribute) is None

    await manager.close()
    for operation in operations:
        operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_cancelled_during_detach_still_attempts_page_context_browser_and_runtime():
    manager = BrowserManager()
    entered = asyncio.Event()
    blocked = asyncio.Event()

    async def detach():
        entered.set()
        await blocked.wait()

    manager._request_session = SimpleNamespace(detach=detach)
    operations = []
    for attribute, method in RESOURCES[1:]:
        operation = AsyncMock()
        setattr(manager, attribute, SimpleNamespace(**{method: operation}))
        operations.append(operation)

    cleanup = asyncio.create_task(manager.close())
    await entered.wait()
    cleanup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cleanup
    assert cleanup.cancelled()
    for (attribute, _), operation in zip(RESOURCES[1:], operations, strict=True):
        operation.assert_awaited_once()
        assert getattr(manager, attribute) is None
