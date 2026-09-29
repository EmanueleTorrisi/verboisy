"""First-use browser setup; imports and --help never download a browser."""

import asyncio
import sys
from pathlib import Path

from filelock import FileLock

from verboisy.utils.exceptions import NavigationError


def _install(executable: Path) -> None:
    import subprocess

    # Keep the lock outside the revision, including nested macOS app bundles.
    revision = next(
        (p for p in executable.parents if p.name.startswith("chromium-")),
        executable.parent.parent,
    )
    lock = FileLock(str(revision) + ".verboisy-install.lock")
    Path(lock.lock_file).parent.mkdir(parents=True, exist_ok=True)
    with lock.acquire(timeout=600):
        if executable.is_file():
            return
        print("Verboisy: installing the matching Chromium browser (first use).", file=sys.stderr)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise NavigationError(
                "Chromium download failed. Check network access or run verboisy setup."
            ) from None
        if result.returncode or not executable.is_file():
            raise NavigationError(
                "Chromium installation failed. Check network/proxy settings and re"
                "try verboisy setup. No model request was made."
            )


async def ensure_browser(executable: str, auto: bool) -> None:
    path = Path(executable)
    if path.is_file():
        return
    if not auto:
        raise NavigationError(
            "Chromium is missing and automatic installation is disabled. Run verboisy setup."
        )
    await asyncio.to_thread(_install, path)
