<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Validation gates

Use Python >=3.11,<3.15. Run from the repository root in its Poetry environment.

```bash
poetry check --lock
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src
poetry run pytest -m 'not browser and not live' --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
poetry run mkdocs build --strict
poetry run pip-audit --local
poetry build
```

Coverage remains a code-execution gate, not evidence of live extraction accuracy.
The new tests replace obsolete model-FINISH/raw-record tests with provenance, scope,
resume, conflict, partial-export and failure contracts. Retained schema, network,
export, provider-error and browser-lifecycle regressions still run.

Real Chromium checks require the actual browser and Linux native libraries:

```bash
poetry run verboisy setup
poetry run pytest -m browser -q
```

On a fresh Linux CI machine, provision native libraries with
`poetry run python -m playwright install --with-deps chromium` first. Keep the sandbox
enabled in production and in non-root CI. `TEST_BROWSER_SANDBOX=false` is only for an
explicitly isolated root-owned test environment and is not release evidence of sandboxing.

Opt-in paid model evaluation (credentials are read from your own environment):

```bash
poetry run python scripts/evaluate.py --live --repetitions 3 \
  --mode evidence baseline --output ../verboisy-live-evaluation.json
```

Do not publish until all positive fixture datasets match the gold records, all critical
negative controls reject unsupported values, and there are no false completion claims.
Then run a held-out, manually annotated sample from each site class you intend to
support, across at least two schemas per class and repeated runs. Measure field precision,
record recall, false completion, rejected/conflicting records, latency and cost. Set the
release thresholds before evaluating: recommended initial goals are >=99% supported-field
precision, >=95% recall on finite annotated sources, and zero known critical negative
control failures. These thresholds define acceptance criteria; measured results must be recorded separately.

For an ML use case, additionally review source permissions, leakage, label quality,
duplicates, missingness, sampling bias and temporal drift. A schema-valid dataset alone
is not suitable evidence for training or scientific conclusions.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
