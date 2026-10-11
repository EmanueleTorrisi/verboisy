# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""A green compiled-test run must describe the current production and test sources."""

import hashlib
import json
from unittest.mock import patch

import pytest
from verboisy.evidence import native_configuration as inspection


@pytest.fixture
def builds(tmp_path, monkeypatch):
    directory = tmp_path / "build/native"
    directory.mkdir(parents=True)
    monkeypatch.setenv("VERBOISY_NATIVE_QUOTE_DIR", str(directory))
    monkeypatch.setenv("VERBOISY_QUOTE_MATCHER", "python")
    monkeypatch.setattr(inspection, "_ROOT", tmp_path)
    for name in set(inspection._SOURCES + inspection._TEST_SOURCES):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    binary = inspection.native_module_path()
    test_binary = binary.with_name(binary.name.replace("_native", "_native_tests", 1))
    metadata = {}
    for name, module, sources, version, filename in [
        ("production", binary, inspection._SOURCES, "2", "quote-build.json"),
        ("tests", test_binary, inspection._TEST_SOURCES, "1", "quote-tests-build.json"),
    ]:
        module.write_bytes(name.encode())
        data = {
            "build_version": version,
            "purpose": "direct_cpp_tests",
            "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
            "source_hashes": {
                source: hashlib.sha256((tmp_path / source).read_bytes()).hexdigest()
                for source in sources
            },
        }
        metadata[name] = directory / filename
        metadata[name].write_text(json.dumps(data))
    return tmp_path, test_binary, metadata


def test_current_builds_are_inspected_without_loading(builds):
    with patch("verboisy.evidence.quote_match._load_native_export", side_effect=AssertionError):
        reports = inspection.inspect_native_builds()
    assert set(reports) == {"production", "tests"}
    for report in reports.values():
        assert report["binary_matches_metadata"] is True
        assert report["sources_match_metadata"] is True
    assert reports["tests"]["module_path"].endswith(builds[1].name)


@pytest.mark.parametrize("artifact", ["binary", "metadata", "source", "changed_source"])
def test_test_build_drift_is_independent_of_production(builds, artifact):
    root, binary, metadata = builds
    source = root / "native/tests/test_quote_batch.cpp"
    if artifact == "binary":
        binary.write_bytes(b"different binary")
    elif artifact == "metadata":
        metadata["tests"].unlink()
    elif artifact == "source":
        source.unlink()
    else:
        source.write_bytes(b"changed assertion")
    reports = inspection.inspect_native_builds()
    assert reports["production"]["sources_match_metadata"] is True
    assert reports["production"]["binary_matches_metadata"] is True
    if artifact == "binary":
        assert reports["tests"]["binary_matches_metadata"] is False
    elif artifact == "metadata":
        assert reports["tests"]["metadata_present"] is False
    else:
        assert reports["tests"]["sources_match_metadata"] is False


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("purpose", "production", "purpose"),
        ("build_version", "2", "build_version 1"),
        ("source_hashes", {"../../secret": "0" * 64}, "source keys"),
    ],
)
def test_test_manifest_identity_and_paths_are_checked(builds, field, value, message):
    _, _, metadata = builds
    data = json.loads(metadata["tests"].read_text())
    data[field] = value
    metadata["tests"].write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        inspection.inspect_native_builds()
