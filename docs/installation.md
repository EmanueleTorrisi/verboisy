<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Install once. Run `verboisy`.

Python **3.11–3.14** is required. The package already exposes the `verboisy` console
entry point. Poetry is a development tool; it is not part of the installed command.
Execution requires the [written usage rights](licensing.md).

| Need | Installation | Usage |
| --- | --- | --- |
| Develop and test this repository | Bootstrap, then activate `.venv` | `verboisy run …` |
| Use the CLI outside a project | pipx with an authorized wheel or checkout | `verboisy run …` |
| Import the Python API | pip in your application's virtual environment | `from verboisy import run` |
| Install a future public release | `pipx install verboisy` or pip in a virtual environment | Available only after publication |

pip and pipx are installers. **PyPI is the registry you publish to.** There is no
separate upload to pip or pipx. Public availability does not change the license.

## Development checkout

Run from the repository root in Bash on macOS/Linux:

```bash
bash scripts/bootstrap.sh
source .venv/bin/activate
verboisy --help
python examples/local_quickstart.py
```

Development tools go under ignored `build/release-tools`; project dependencies go
in `.venv`. The quickstart verifies two labelled synthetic records, saving inputs,
output, database and evidence under `example-runs/`. It needs no model or browser.

For ordinary use without development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

Activate this environment in each new shell. For a delivered wheel, substitute its
actual path for `.`. Install in the application's own environment for Python imports.

## CLI with pipx

With pipx installed, run from an authorized checkout:

```bash
pipx install .
pipx ensurepath
export PATH="$HOME/.local/bin:$PATH"
verboisy --help
```

To install pipx without changing the system Python:

```bash
python3 -m venv "$HOME/.local/share/verboisy-tools"
"$HOME/.local/share/verboisy-tools/bin/python" -m pip install pipx
"$HOME/.local/share/verboisy-tools/bin/python" -m pipx ensurepath
"$HOME/.local/share/verboisy-tools/bin/python" -m pipx install .
export PATH="$HOME/.local/bin:$PATH"
verboisy --help
```

Once an authorized public release exists, users with pipx can run:

```bash
pipx install verboisy
verboisy --help
# Later, for a new published release:
pipx upgrade verboisy
```

pipx isolates the CLI; its packages are not importable from an unrelated interpreter.

## Windows

The bootstrap is a Bash script for macOS/Linux. Ordinary PowerShell installation:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\verboisy.exe --help
```

For Windows development, install Poetry, set `$env:POETRY_VIRTUALENVS_IN_PROJECT="true"`,
run `poetry install`, and invoke the environment's Python and CLI explicitly.

## Browser and model configuration

For web research:

```bash
verboisy setup
verboisy model-config
verboisy run --help
```

Chromium may need administrator-installed system libraries on Linux. See
[validation](validation.md) for the Playwright setup command. Keep credentials in
your private environment or `.env`; `model-config` reports presence, not values.
See [providers](providers.md). Local ingestion needs explicit directory grants in
`DATASET_LOCAL_ROOTS`. Normal installation requires no C++ compiler; optional native
acceleration has [separate build steps](native.md).

## Absolute URLs

The root README is also PyPI's package description. Its images and repository links
use absolute HTTPS URLs so they resolve away from GitHub. The translations follow
the same convention. Other Markdown can keep relative links: GitHub and MkDocs
resolve them within their document trees. CLI filesystem paths remain filesystem
paths. See the [PyPA README guide](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/).
