# Validation and release workflow

Execute these commands from the repository root after installing Poetry 2.5.1 and
Python 3.11 or later. The supplied .python-version selects 3.11.9; the audit used
that version. CI also covers newer Python minors, whose results must be checked in CI.

```bash
poetry install
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src
poetry run pytest -m "not browser" --cov=src --cov-report=term-missing
poetry run pip-audit --local
poetry run mkdocs build --strict
poetry build
```

Success means zero exit status. Coverage must meet the existing 80% threshold.
The audit's offline tests replace browser/model decisions where stated; they do
not establish real model accuracy. The local HTTP test uses the actual LiteLLM
transport with a stub model response.

Required Chromium gate on Linux/macOS:

```bash
poetry run playwright install --with-deps chromium
VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m browser -v
```

PowerShell equivalent for the second command:

```powershell
$env:VERBOISY_REQUIRE_BROWSER = "1"
poetry run pytest -m browser -v
Remove-Item Env:VERBOISY_REQUIRE_BROWSER
```

The browser fixture uses a local HTTP server and explicitly disables Chromium's OS
sandbox inside the test process only. Product defaults remain sandboxed. Test the
default sandbox separately on the intended deployment OS/container.

If installation fails, resolve the interpreter/package error before proceeding.
If Chromium cannot download or launch, the browser gate is blocked, not passed.
If pip-audit cannot reach the advisory service, no clean-security claim follows.
If a test fails, retain the traceback and database; do not relax assertions or
mark the run completed merely to produce an export.

Run [live acceptance](demo.md) with the intended model/provider after these checks.
Build/install the wheel in a fresh virtual environment and test
`python -m verboisy --help` and the documented source examples.

The publication workflow repeats tests/build on the release tag and checks that
`v<version>` matches pyproject.toml. Configure trusted publishing with PyPI and the
protected `pypi` GitHub environment before publishing. No release was published
as part of the audit. A green local suite is not a substitute for a green release
workflow, live acceptance, and deployment-specific checks.
