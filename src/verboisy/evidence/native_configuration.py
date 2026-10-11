# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Inspect optional build fingerprints without importing executable native code."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from verboisy.evidence.quote_match import native_module_path

_ROOT = Path(__file__).resolve().parents[3]
_SOURCES = (
    "native/python_module.cpp",
    "native/quote_match.cpp",
    "native/unicode_boundaries.cpp",
    "native/quote_batch.cpp",
    "native/quote_match.hpp",
    "native/unicode_boundaries.hpp",
    "native/quote_batch.hpp",
)
_TEST_SOURCES = (
    *tuple(name for name in _SOURCES if name != "native/python_module.cpp"),
    "native/tests/python_test_module.cpp",
    "native/tests/test_quote_match.cpp",
    "native/tests/test_unicode_boundaries.cpp",
    "native/tests/test_quote_batch.cpp",
    "native/tests/test_support.hpp",
)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _metadata(
    path: Path, sources: tuple[str, ...], version: str, purpose: str | None
) -> dict[str, str]:
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Native build metadata exceeds 64 KiB")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid native build metadata JSON") from exc
    if not isinstance(data, dict) or data.get("build_version") != version:
        raise ValueError(f"Native build metadata requires build_version {version}")
    if purpose is not None and data.get("purpose") != purpose:
        raise ValueError("Native test metadata requires purpose direct_cpp_tests")
    source_hashes = data.get("source_hashes")
    # The metadata describes known inputs; it must never choose files to inspect.
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(sources):
        raise ValueError("Native build metadata has unexpected source keys")
    hashes = [data.get("module_sha256"), *source_hashes.values()]
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes
    ):
        raise ValueError("Native build metadata has invalid SHA-256 fingerprints")
    return {"module_sha256": data["module_sha256"], **source_hashes}


def inspect_native_configuration() -> dict[str, object]:
    """Read shell selection and local files; no loader, settings or ledger is used."""
    selected = os.environ.get("VERBOISY_QUOTE_MATCHER", "python")
    if selected not in ("python", "regex", "native"):
        raise ValueError("VERBOISY_QUOTE_MATCHER must be python, regex or native")
    directory = os.environ.get("VERBOISY_NATIVE_QUOTE_DIR", "")
    if directory and not Path(directory).is_absolute():
        raise ValueError("VERBOISY_NATIVE_QUOTE_DIR must be an absolute directory")
    binary = native_module_path(directory)
    files = _inspect_build(binary, "quote-build.json", _SOURCES, "2", None)
    return {
        "configuration_version": "1",
        "selected_backend": selected,
        "default_backend": "python",
        "configuration_source": "shell_environment",
        "native_build_platform_supported": sys.implementation.name == "cpython"
        and sys.platform in ("linux", "darwin"),
        **files,
        "binary_loaded": False,
        "loadability": "not_checked",
        "automatic_fallback": False,
    }


def _inspect_build(
    binary: Path, metadata_name: str, sources: tuple[str, ...], version: str, purpose: str | None
) -> dict[str, object]:
    metadata = binary.parent / metadata_name
    binary_present = binary.is_file()
    metadata_present = metadata.is_file()
    binary_match: bool | None = None
    source_match: bool | None = None
    missing: list[str] = []
    changed: list[str] = []
    if metadata_present:
        hashes = _metadata(metadata, sources, version, purpose)
        if binary_present:
            binary_match = _digest(binary) == hashes["module_sha256"]
        for name in sources:
            path = _ROOT / name
            if not path.is_file():
                missing.append(name)
            elif _digest(path) != hashes[name]:
                changed.append(name)
        source_match = not missing and not changed
    return {
        "module_path": str(binary),
        "metadata_path": str(metadata),
        "binary_present": binary_present,
        "metadata_present": metadata_present,
        "binary_matches_metadata": binary_match,
        "sources_match_metadata": source_match,
        "missing_sources": missing,
        "changed_sources": changed,
    }


def inspect_native_builds() -> dict[str, dict[str, object]]:
    """Inspect both fixed build manifests before the test gate executes native code."""
    production = inspect_native_configuration()
    binary = native_module_path()
    test_binary = binary.with_name(
        binary.name.replace("_verboisy_quote_native", "_verboisy_quote_native_tests", 1)
    )
    tests = _inspect_build(
        test_binary, "quote-tests-build.json", _TEST_SOURCES, "1", "direct_cpp_tests"
    )
    return {"production": production, "tests": tests}
