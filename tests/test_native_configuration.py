# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Fingerprint inspection cannot execute a library or authorize native loading."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from verboisy.cli.main import app
from verboisy.evidence import native_configuration as inspection


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.delenv("VERBOISY_QUOTE_MATCHER", raising=False)
    directory = tmp_path / "build/native"
    directory.mkdir(parents=True)
    monkeypatch.setenv("VERBOISY_NATIVE_QUOTE_DIR", str(directory))
    monkeypatch.setattr(inspection, "_ROOT", tmp_path)
    sources = {}
    for name in inspection._SOURCES:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(name.encode())
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    binary = inspection.native_module_path()
    binary.write_bytes(b"not executable native code")
    metadata = directory / "quote-build.json"
    data = {
        "build_version": "2",
        "module_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_hashes": sources,
        "compiler": "untrusted compiler details",
    }
    metadata.write_text(json.dumps(data))
    return tmp_path, binary, metadata, data


def test_matching_fingerprints_do_not_claim_loadability(build):
    root, binary, metadata, _ = build
    with patch("verboisy.evidence.quote_match._load_native_export", side_effect=AssertionError):
        report = inspection.inspect_native_configuration()
    assert report["selected_backend"] == report["default_backend"] == "python"
    assert report["module_path"] == str(binary)
    assert report["metadata_path"] == str(metadata)
    assert report["binary_matches_metadata"] is True
    assert report["sources_match_metadata"] is True
    assert report["binary_loaded"] is report["automatic_fallback"] is False
    assert report["loadability"] == "not_checked"
    assert "untrusted" not in json.dumps(report)
    assert not (root / "verboisy.db").exists()


@pytest.mark.parametrize("selected", ["python", "regex", "native"])
def test_missing_artifacts_and_explicit_selection(build, monkeypatch, selected):
    _, binary, metadata, _ = build
    binary.unlink()
    metadata.unlink()
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", selected)
    report = inspection.inspect_native_configuration()
    assert report["selected_backend"] == selected
    assert report["binary_present"] is report["metadata_present"] is False
    assert report["binary_matches_metadata"] is report["sources_match_metadata"] is None
    assert report["missing_sources"] == report["changed_sources"] == []


def test_missing_binary_with_valid_metadata(build):
    _, binary, _, _ = build
    binary.unlink()
    report = inspection.inspect_native_configuration()
    assert report["binary_matches_metadata"] is None
    assert report["sources_match_metadata"] is True


def test_binary_and_source_drift_are_separately_reported(build):
    root, binary, _, _ = build
    binary.write_bytes(b"changed")
    (root / inspection._SOURCES[0]).unlink()
    (root / inspection._SOURCES[1]).write_bytes(b"changed")
    report = inspection.inspect_native_configuration()
    assert report["binary_matches_metadata"] is False
    assert report["sources_match_metadata"] is False
    assert report["missing_sources"] == [inspection._SOURCES[0]]
    assert report["changed_sources"] == [inspection._SOURCES[1]]


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"x" * 65537, "exceeds"),
        (b"{broken", "JSON"),
        (b"\xff", "JSON"),
        (b"[]", "build_version"),
        (b'{"build_version":"1"}', "build_version"),
        (b'{"build_version":"2","source_hashes":[]}', "source keys"),
        (b'{"build_version":"2","source_hashes":{"../secret":"x"}}', "source keys"),
    ],
)
def test_invalid_metadata_is_rejected_before_source_reads(build, raw, message):
    _, _, metadata, _ = build
    metadata.write_bytes(raw)
    with (
        patch.object(inspection, "_digest", side_effect=AssertionError("unexpected read")),
        pytest.raises(ValueError, match=message),
    ):
        inspection.inspect_native_configuration()


@pytest.mark.parametrize("value", [None, 42, "bad", "F" * 64])
@pytest.mark.parametrize("field", ["module", "source"])
def test_hash_validation(build, value, field):
    _, _, metadata, data = build
    if field == "module":
        data["module_sha256"] = value
    else:
        data["source_hashes"][inspection._SOURCES[0]] = value
    metadata.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="SHA-256"):
        inspection.inspect_native_configuration()


@pytest.mark.parametrize(
    "implementation, platform, supported",
    [
        ("cpython", "linux", True),
        ("cpython", "darwin", True),
        ("cpython", "win32", False),
        ("pypy", "linux", False),
    ],
)
def test_platform_eligibility_is_not_a_load_test(
    build, monkeypatch, implementation, platform, supported
):
    monkeypatch.setattr(
        inspection,
        "sys",
        SimpleNamespace(implementation=SimpleNamespace(name=implementation), platform=platform),
    )
    assert inspection.inspect_native_configuration()["native_build_platform_supported"] is supported


def test_cli_ignores_dotenv_and_never_loads_settings_or_native_code(build, monkeypatch):
    root, _, _, _ = build
    monkeypatch.chdir(root)
    (root / ".env").write_text("VERBOISY_QUOTE_MATCHER=native\nLITELLM_MODEL=PRIVATE\n")
    with (
        patch("verboisy.cli.main.Settings", side_effect=AssertionError("settings")),
        patch(
            "verboisy.evidence.quote_match._load_native_export",
            side_effect=AssertionError("loader"),
        ),
        patch("verboisy.llm.client._complete", side_effect=AssertionError("provider")),
        patch("verboisy.storage.research.ResearchStore", side_effect=AssertionError("ledger")),
    ):
        result = CliRunner().invoke(app, ["native-config"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["selected_backend"] == "python"
    assert "PRIVATE" not in result.output


@pytest.mark.parametrize(
    "variable, value, message",
    [
        ("VERBOISY_QUOTE_MATCHER", "invalid", "must be python"),
        ("VERBOISY_NATIVE_QUOTE_DIR", "relative", "absolute directory"),
    ],
)
def test_cli_configuration_errors(build, monkeypatch, variable, value, message):
    monkeypatch.setenv(variable, value)
    result = CliRunner().invoke(app, ["native-config"])
    assert result.exit_code == 1
    assert message in result.output


def test_cli_reports_read_failure(build):
    with patch.object(inspection, "_digest", side_effect=OSError("Cannot read native file")):
        result = CliRunner().invoke(app, ["native-config"])
    assert result.exit_code == 1
    assert "Cannot read native file" in result.output


def test_default_module_location_without_override(build, monkeypatch):
    monkeypatch.delenv("VERBOISY_NATIVE_QUOTE_DIR")
    report = inspection.inspect_native_configuration()
    assert report["module_path"] == str(inspection.native_module_path(""))
