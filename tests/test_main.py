# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Tests for the python -m verboisy entry point."""

import importlib
import runpy
from unittest.mock import Mock


def test_main_module(monkeypatch):
    """Test that python -m verboisy invokes the CLI app."""

    cli_main = importlib.import_module("verboisy.cli.main")

    mock_app = Mock()

    monkeypatch.setattr(
        cli_main,
        "app",
        mock_app,
    )

    runpy.run_module(
        "verboisy.__main__",
        run_name="__main__",
    )

    mock_app.assert_called_once_with()
