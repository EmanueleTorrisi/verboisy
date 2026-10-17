#!/usr/bin/env bash
# Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms.
# Run from an authorized source checkout. No global Python packages are changed.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 15), "Use Python 3.11–3.14"'
python3 -m venv build/release-tools
build/release-tools/bin/python -m pip install --upgrade pip
build/release-tools/bin/python -m pip install 'poetry==2.5.1' twine pipx
unset VIRTUAL_ENV
export POETRY_VIRTUALENVS_IN_PROJECT=true
build/release-tools/bin/poetry check --lock
build/release-tools/bin/poetry install
printf '\nReady. Run: source .venv/bin/activate\nThen: verboisy --help\n'
