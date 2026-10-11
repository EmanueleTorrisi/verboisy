<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Maintaining Verboisy

Verboisy is currently maintained by its author as a private project. External code
contributions are not currently accepted. This guide documents the maintainer's
workflow; it does not grant or change software reuse permissions under LICENSE.

Bug reports, feature suggestions and security disclosures remain useful when the
project's issue/reporting channels are made available. Please do not submit code or
pull requests unless the maintainer has explicitly invited that contribution.

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
and actual verification in change notes.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md). Follow the
[Code of Conduct](CODE_OF_CONDUCT.md), remove secrets from issue logs, and search
existing issues before filing a new report.

## Final candidate workflow

The six implementation batches are followed by the release acceptance campaign,
not by automatic publication. Use `make validate` for the configured full environment
and `make repo-check` for read-only repository consistency. Keep offline fixtures,
real browser tests, native tests and paid research qualification distinct.

The maintainer uses one changed file per commit with a different, meaningful subject
for each file. Review the delivery's file/message plan and follow
[commit policy](../docs/commit-policy.md). Validate the final batch HEAD before pushing;
intermediate per-file commits can depend on later files in the same batch.

Review [release evidence](../docs/release-checklist.md) and
[distribution readiness](../docs/distribution.md). Copyright headers and external
contribution policy do not amend LICENSE. Changes to public distribution terms require
an explicit reviewed decision before visibility or publication is enabled.
