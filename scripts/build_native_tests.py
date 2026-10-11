# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Build the test-only extension containing direct C++ assertions."""

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


def main() -> None:
    if sys.implementation.name != "cpython" or sys.platform not in ("linux", "darwin"):
        raise SystemExit("Native build currently supports CPython on Linux/WSL and macOS only.")
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "native" / name
        for name in ("quote_match.cpp", "unicode_boundaries.cpp", "quote_batch.cpp")
    ]
    headers = [
        root / "native" / name
        for name in ("quote_match.hpp", "unicode_boundaries.hpp", "quote_batch.hpp")
    ]
    sources.extend(
        root / "native/tests" / name
        for name in (
            "python_test_module.cpp",
            "test_quote_match.cpp",
            "test_unicode_boundaries.cpp",
            "test_quote_batch.cpp",
        )
    )
    headers.append(root / "native/tests/test_support.hpp")
    directory = root / "build/native"
    directory.mkdir(parents=True, exist_ok=True)
    filename = "_verboisy_quote_native_tests" + sysconfig.get_config_var("EXT_SUFFIX")
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    if not compiler:
        raise SystemExit("CXX must name a C++ compiler.")
    with tempfile.TemporaryDirectory(prefix="quote-tests-build-", dir=directory) as scratch:
        output = Path(scratch) / filename
        command = [
            *compiler,
            "-std=c++17",
            "-O3",
            "-fPIC",
            "-shared",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I" + sysconfig.get_path("include"),
            *map(str, sources),
            "-o",
            str(output),
        ]
        if sys.platform == "darwin":
            command.extend(["-undefined", "dynamic_lookup"])
        try:
            subprocess.run(command, check=True)
            version = subprocess.run(
                [*compiler, "--version"], check=True, capture_output=True, text=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(
                "Native build failed; install a C++ compiler and CPython headers."
            ) from exc
        metadata = {
            "build_version": "1",
            "purpose": "direct_cpp_tests",
            "python": sys.version,
            "platform": platform.platform(),
            "compiler": version.stdout.splitlines()[0],
            "command": command,
            "source_hashes": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [*sources, *headers]
            },
            "module_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
        # Publish only a completed compilation. Restart any process that already
        # loaded an older extension; shared libraries cannot be hot-reloaded safely.
        output.replace(directory / filename)
        (directory / "quote-tests-build.json").write_text(json.dumps(metadata, indent=2))
    print(directory / filename)


if __name__ == "__main__":
    main()
