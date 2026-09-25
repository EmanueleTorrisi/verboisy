# Contributing to Verboisy

Use Python 3.11 or later and Poetry 2.5.1. The supplied .python-version is 3.11.9.
From the repository root:

```bash
python -m pip install poetry==2.5.1
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src
poetry run pytest -m "not browser" --cov=src
poetry run mkdocs build --strict
poetry build
```

Install Chromium and run the mandatory browser gate before a release:

```bash
poetry run playwright install --with-deps chromium
VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m browser -v
```

Windows contributors can set the environment variable in PowerShell as documented
in [validation.md](../docs/validation.md). Unit tests require no provider key. The HTTP
integration server is a deterministic model stub and must not be presented as a live
model demonstration. [Live acceptance](../docs/demo.md) exercises a real provider.

Add behavior-focused regressions for defects, preserve the public API, and update
README/architecture when behavior changes. Never replace a required browser failure
with a skip in a release gate. Keep changes focused and explain the problem, solution
and actual verification in pull requests.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md). Follow the
[Code of Conduct](CODE_OF_CONDUCT.md), remove secrets from issue logs, and search
existing issues before filing a new report.
