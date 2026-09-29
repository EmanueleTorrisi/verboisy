# Contributing to Verboisy

Use Python 3.11–3.14 and Poetry 2.5.1. The supplied .python-version is 3.11.9.
From the repository root:

```bash
python -m pip install poetry==2.5.1
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src
poetry run pytest -m "not browser and not live" --cov=src --cov-branch --cov-fail-under=100
poetry run mkdocs build --strict
poetry build
```

Install Chromium and run the mandatory browser gate before a release:

```bash
poetry run playwright install --with-deps chromium
VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m browser -v
```

See [validation.md](../docs/validation.md) for release gates. Unit tests require no provider key. The HTTP
integration server is a deterministic model stub and must not be presented as a live
model demonstration. [Live acceptance](../docs/demo.md) exercises a real provider.

Add behavior-focused regressions for defects, preserve the public API, and update
README/architecture when behavior changes. Never replace a required browser failure
with a skip in a release gate. Keep changes focused and explain the problem, solution
and actual verification in pull requests.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md). Follow the
[Code of Conduct](CODE_OF_CONDUCT.md), remove secrets from issue logs, and search
existing issues before filing a new report.
