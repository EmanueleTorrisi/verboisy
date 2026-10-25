#!/usr/bin/env bash
# Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms.
# Run from an authorized source checkout. No global Python packages are changed.
set -euo pipefail
cd -P "$(dirname "$0")/.."
python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 15), "Use Python 3.11–3.14"'
python3 -m venv build/release-tools
build/release-tools/bin/python -m pip install --upgrade pip 'setuptools>=84.1.0'
build/release-tools/bin/python -m pip install 'poetry==2.5.1' twine pipx 'filelock>=4.2.4,<5.0' 'virtualenv>=21.14.10,<22.0'
unset VIRTUAL_ENV
export POETRY_VIRTUALENVS_CREATE=true
export POETRY_VIRTUALENVS_IN_PROJECT=true
build/release-tools/bin/poetry check --lock

# A cached Poetry environment can prevent in-project creation. Create and select
# the local environment explicitly; leave any existing cached environment intact.
if [[ ! -e .venv && ! -L .venv ]]; then
    python3 -m venv .venv
fi
if [[ ! -f .venv/pyvenv.cfg || ! -x .venv/bin/python || ! -f .venv/bin/activate ]]; then
    printf 'Setup stopped: .venv already exists but is incomplete; inspect it before retrying.\n' >&2
    exit 1
fi
.venv/bin/python - <<'PY'
import sys
from pathlib import Path

assert (3, 11) <= sys.version_info[:2] < (3, 15), "Use Python 3.11–3.14 for .venv"
assert sys.prefix != sys.base_prefix, ".venv/bin/python must belong to a virtual environment"
assert Path(sys.prefix).resolve() == Path(".venv").resolve(), "Unexpected .venv interpreter"
PY
export VIRTUAL_ENV="$PWD/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"
build/release-tools/bin/poetry env use "$VIRTUAL_ENV/bin/python"
VERBOISY_POETRY_ENV="$(build/release-tools/bin/poetry env info --path)"
.venv/bin/python - "$VERBOISY_POETRY_ENV" <<'PY'
import sys
from pathlib import Path

assert Path(sys.argv[1]).resolve() == Path(".venv").resolve(), "Poetry did not select .venv"
PY
build/release-tools/bin/poetry install
# Refresh tooling seeded by venv separately from the application dependency lock.
.venv/bin/python -m pip install --upgrade 'setuptools>=84.1.0'
test -x .venv/bin/verboisy
printf '\nReady. Run: source .venv/bin/activate\nThen: verboisy --help\n'
