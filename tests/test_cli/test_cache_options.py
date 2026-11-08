# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

import hashlib
import json
from types import SimpleNamespace

from typer.testing import CliRunner
from verboisy.cache import ProjectCache
from verboisy.cache_policy import CachePolicy
from verboisy.cli.main import app


def test_cache_inspection_without_creation_or_research(tmp_path):
    result = CliRunner().invoke(
        app, ["cache", "--directory", str(tmp_path / "missing"), "--scope", "team"]
    )
    assert result.exit_code == 0 and json.loads(result.stdout)["exists"] is False
    assert not (tmp_path / "missing").exists()


def test_cache_stats_clear_and_invalid_directory_are_controlled(tmp_path):
    policy = CachePolicy(tmp_path / "cache", "team")
    with ProjectCache(policy) as cache:
        cache.put(hashlib.sha256(b"one").hexdigest(), {"value": 1})
    args = ["cache", "--directory", str(policy.directory), "--scope", "team"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0 and json.loads(result.stdout)["entries"] == 1
    result = CliRunner().invoke(app, [*args, "--clear"])
    assert result.exit_code == 0 and json.loads(result.stdout)["cleared"] is True
    result = CliRunner().invoke(app, ["cache", "--directory", "relative", "--scope", "team"])
    assert result.exit_code == 1


def test_cache_inspection_refuses_linked_policy_inputs(tmp_path, monkeypatch):
    import verboisy.cache_policy as module

    linked = SimpleNamespace(directory=SimpleNamespace(is_symlink=lambda: True))
    monkeypatch.setattr(module, "CachePolicy", lambda *_args: linked)
    result = CliRunner().invoke(app, ["cache", "--directory", str(tmp_path), "--scope", "team"])
    assert result.exit_code == 1


def test_run_passes_explicit_cache_settings_without_changing_preview(tmp_path, monkeypatch):
    import verboisy.cli.main as main

    seen = []

    def run(**kwargs):
        seen.append(kwargs["config"])
        return SimpleNamespace(
            run_id="test",
            completed=True,
            status="COMPLETED",
            records=[],
            notices=(),
            export_paths=(),
            manifest_paths=(),
            proof_path=None,
            inferred_schema=None,
            dataset_consistency=None,
        )

    monkeypatch.setattr(main, "run", run)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--goal",
            "Names",
            "--schema",
            "[name]",
            "--no-animation",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--cache-scope",
            "team",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen[0].cache_directory == tmp_path / "cache" and seen[0].cache_scope == "team"
    assert not (tmp_path / "cache").exists()
    monkeypatch.setenv("CACHE_DIRECTORY", str(tmp_path / "cache"))
    monkeypatch.setenv("CACHE_SCOPE", "team")
    bypassed = CliRunner().invoke(
        app, ["run", "--goal", "Names", "--schema", "[name]", "--no-animation", "--no-cache"]
    )
    assert bypassed.exit_code == 0, bypassed.output
    assert seen[-1].cache_policy() is None
    conflict = CliRunner().invoke(
        app, ["run", "--no-animation", "--no-cache", "--cache-scope", "team"]
    )
    assert conflict.exit_code == 1
