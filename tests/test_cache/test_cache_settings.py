# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Explicit cache configuration and export protection without storage access."""

import pytest
from pydantic import ValidationError
from verboisy.utils.config import Settings


def test_disabled_is_default_and_creates_no_storage(tmp_path):
    config = Settings(_env_file=None)
    assert config.cache_policy() is None and config.input_files() == ()
    assert list(tmp_path.iterdir()) == []


def test_cache_scope_required_and_file_paths_are_protected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cache_directory=tmp_path / "cache")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cache_directory="relative", cache_scope="team")
    config = Settings(_env_file=None, cache_directory=tmp_path / "cache", cache_scope="team")
    assert config.input_files() == config.cache_policy().protected_paths
    assert not config.cache_directory.exists()
    from verboisy.storage.path_safety import validate_output_paths

    for path in config.input_files():
        with pytest.raises(ValueError):
            validate_output_paths([path], config.input_files())


@pytest.mark.parametrize(
    "field", ["cache_max_bytes", "cache_max_entry_bytes", "cache_ttl_seconds", "cache_max_entries"]
)
def test_boolean_limits_are_not_coerced(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: True})


def test_environment_policy_is_validated_without_opening_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIRECTORY", str(tmp_path / "cache"))
    monkeypatch.setenv("CACHE_SCOPE", "procurement")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    config = Settings(_env_file=None)
    assert config.cache_policy().ttl_seconds == 60
    assert not config.cache_directory.exists()
