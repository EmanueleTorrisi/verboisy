# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Cancellable first-use setup with owned subprocess groups and a separate deadline.

Import and help perform no installation. Output goes to DEVNULL, avoiding both
unbounded buffers and private proxy diagnostics in public errors.
"""

import asyncio
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

from filelock import FileLock, Timeout

from verboisy.utils.exceptions import NavigationError

INSTALL_TIMEOUT = 600.0


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Reap only the owned installer/group, escalating after two seconds."""
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        await asyncio.wait_for(process.wait(), 2)
    except (TimeoutError, ProcessLookupError):
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(killer.wait(), 2)
            except TimeoutError:
                killer.kill()
                await killer.wait()
        await asyncio.wait_for(process.wait(), 2)


async def _install(executable: Path) -> None:
    """Acquire asynchronously and install within a single provisioning ceiling."""
    revision = next(
        (p for p in executable.parents if p.name.startswith("chromium-")), executable.parent.parent
    )
    lock = FileLock(str(revision) + ".verboisy-install.lock")
    Path(lock.lock_file).parent.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        async with asyncio.timeout(INSTALL_TIMEOUT):
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    await asyncio.sleep(0.05)
            if executable.is_file():
                return
            options = (
                {"start_new_session": True}
                if os.name == "posix"
                else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}
            )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "playwright",
                "install",
                "chromium",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **options,
            )
            await process.wait()
            if process.returncode or not executable.is_file():
                raise NavigationError(
                    "Chromium installation failed. Check network settings and run verboisy setup. "
                    "No model request was made."
                )
            return
    except (OSError, TimeoutError):
        raise NavigationError(
            "Chromium setup timed out or failed; check network access and run verboisy setup. "
            "No model request was made."
        ) from None
    finally:
        try:
            if process is not None:
                await _stop(process)
        finally:
            lock.release()


async def ensure_browser(executable: str, auto: bool) -> None:
    path = Path(executable)
    if path.is_file():
        return
    if not auto:
        raise NavigationError(
            "Chromium is missing and automatic installation is disabled. Run verboisy setup."
        )
    await _install(path)
