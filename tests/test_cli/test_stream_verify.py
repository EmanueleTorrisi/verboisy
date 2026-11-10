# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Verification is discoverable and fails with a controlled exit status."""

import json

from typer.testing import CliRunner
from verboisy import __version__
from verboisy.cli.main import app
from verboisy.streaming.analytics_verify import AnalyticsVerification


def test_version_and_analytical_capabilities():
    runner = CliRunner()
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert version.stdout.strip() == __version__
    formats = runner.invoke(app, ["formats"])
    assert formats.exit_code == 0
    capabilities = json.loads(formats.stdout)["analytical_bundles"]
    assert capabilities["verify_command"] == "verboisy stream-verify"
    assert capabilities["requires_ledger_to_verify"] is False


def test_stream_verify_passes_explicit_options_and_prints_json(tmp_path, monkeypatch):
    seen = []

    def verify(directory, **options):
        seen.append((directory, options))
        return AnalyticsVerification("0" * 64, True, "jsonl.gz", 2, 2, 2, 1, 1024, 900)

    monkeypatch.setattr("verboisy.streaming.analytics_verify.verify_stream_analytics", verify)
    result = CliRunner().invoke(
        app,
        [
            "stream-verify",
            str(tmp_path),
            "--manifest-sha256",
            "0" * 64,
            "--require-row-checks",
            "--max-bundle-bytes",
            "2048",
            "--max-decoded-bytes",
            "4096",
            "--max-row-bytes",
            "1024",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data_rows_verified"] == 2
    assert seen == [
        (
            tmp_path,
            {
                "expected_manifest_sha256": "0" * 64,
                "require_row_checks": True,
                "max_bundle_bytes": 2048,
                "max_decoded_bytes": 4096,
                "max_row_bytes": 1024,
            },
        )
    ]


def test_stream_verify_refuses_missing_bundle_without_traceback(tmp_path):
    result = CliRunner().invoke(app, ["stream-verify", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert "Traceback" not in result.output


def test_stream_verify_interrupt_is_a_controlled_exit(tmp_path, monkeypatch):
    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("verboisy.streaming.analytics_verify.verify_stream_analytics", interrupt)
    result = CliRunner().invoke(app, ["stream-verify", str(tmp_path)])
    assert result.exit_code == 130


def test_setup_can_check_cached_browser_without_provisioning(monkeypatch):
    events = []

    class CachedBrowser:
        def __init__(self, config):
            events.append(config.browser_auto_install)

        async def start(self):
            events.append("start")

        async def close(self):
            events.append("close")

    monkeypatch.setattr("verboisy.browser.context.BrowserManager", CachedBrowser)
    result = CliRunner().invoke(app, ["setup", "--no-install"])
    assert result.exit_code == 0
    assert events == [False, "start", "close"]
