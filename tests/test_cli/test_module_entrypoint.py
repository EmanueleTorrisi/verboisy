# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Exercise the executable CLI module without research or provider requests."""

import runpy
import sys
from pathlib import Path

import pytest
import verboisy.cli.main as cli


def test_cli_module_entrypoint_displays_help(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verboisy", "--help"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(Path(cli.__file__)), run_name="__main__")
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "Usage" in output
    assert "Verboisy turns a research goal" in output
