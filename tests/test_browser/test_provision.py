# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Provisioning cancellation terminates its owned process group and releases the lock."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from verboisy.browser import provision
from verboisy.utils.exceptions import NavigationError


async def test_cancellation_stops_owned_group(tmp_path, monkeypatch):
    path = tmp_path / "chromium-123" / "bin" / "chrome"
    wait = AsyncMock(side_effect=[asyncio.CancelledError(), 0])
    process = SimpleNamespace(pid=123456, returncode=None, wait=wait)
    transport = AsyncMock(return_value=process)
    monkeypatch.setattr(provision.asyncio, "create_subprocess_exec", transport)
    kill = Mock()
    monkeypatch.setattr(provision.os, "killpg", kill)
    with pytest.raises(asyncio.CancelledError):
        await provision.ensure_browser(str(path), True)
    assert transport.await_args.kwargs["start_new_session"] is True
    kill.assert_called_once_with(123456, provision.signal.SIGTERM)
    assert wait.await_count == 2


async def test_install_lock_timeout_is_safe(tmp_path, monkeypatch):
    from filelock import FileLock

    path = tmp_path / "chromium-123" / "bin" / "chrome"
    lock = FileLock(str(tmp_path / "chromium-123") + ".verboisy-install.lock")
    monkeypatch.setattr(provision, "INSTALL_TIMEOUT", 0.01)
    with lock, pytest.raises(NavigationError, match="timed out"):
        await provision.ensure_browser(str(path), True)


async def test_successful_install_checks_executable_and_releases_lock(tmp_path, monkeypatch):
    from filelock import FileLock

    path = tmp_path / "chromium-123" / "bin" / "chrome"
    process = SimpleNamespace(returncode=0)

    async def install_files():
        path.parent.mkdir(parents=True)
        path.write_bytes(b"installed executable fixture")
        return 0

    process.wait = AsyncMock(side_effect=install_files)
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(provision.asyncio, "create_subprocess_exec", create)
    await provision.ensure_browser(str(path), True)
    assert path.is_file()
    create.assert_awaited_once()
    process.wait.assert_awaited_once()
    lock = FileLock(str(tmp_path / "chromium-123") + ".verboisy-install.lock")
    with lock.acquire(timeout=0):
        assert lock.is_locked


@pytest.mark.parametrize(
    "platform,lookup,killer_timeout",
    [("posix", False, False), ("posix", True, False), ("nt", False, False), ("nt", False, True)],
)
async def test_owned_shutdown_escalation(monkeypatch, platform, lookup, killer_timeout):
    process = SimpleNamespace(
        pid=123456,
        returncode=None,
        wait=AsyncMock(side_effect=[0] if lookup else [TimeoutError(), 0]),
        terminate=Mock(),
    )
    killpg = Mock(side_effect=ProcessLookupError() if lookup else None)
    monkeypatch.setattr(provision, "os", SimpleNamespace(name=platform, killpg=killpg))
    killer = SimpleNamespace(
        wait=AsyncMock(side_effect=[TimeoutError(), 0] if killer_timeout else [0]), kill=Mock()
    )
    create = AsyncMock(return_value=killer)
    monkeypatch.setattr(provision.asyncio, "create_subprocess_exec", create)
    await provision._stop(process)
    if platform == "posix":
        assert killpg.call_count == 2
    else:
        process.terminate.assert_called_once()
        assert create.await_args.args == ("taskkill", "/PID", "123456", "/T", "/F")
        if killer_timeout:
            killer.kill.assert_called_once()


async def test_real_owned_posix_process_stops():
    import os
    import sys

    if os.name != "posix":
        return
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)", start_new_session=True
    )
    await provision._stop(process)
    assert process.returncode is not None
