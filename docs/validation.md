<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering validation

Verboisy 2.0.0 uses Python 3.11.5 or later through Python 3.14 and Poetry for development. Execution,
including development tests, requires the permissions described in [licensing](licensing.md).

## Standard checks

For the source-bound release report, after `bash scripts/bootstrap.sh`:

```bash
source .venv/bin/activate
python scripts/verify_release.py --native --audit --package
```

The verifier records each outcome and artifact checksum. See [release qualification](release.md)
for source-bound review and package selection. The Make targets provide the same
engineering checks as individual commands.

```bash
make validate
```

This target runs lint, formatting, type checks, offline statement/branch coverage,
real browser tests, dependency auditing, strict documentation, package builds and
repository consistency. `make repo-check` checks local document links, source headers,
version/license metadata and publication guards without contacting providers.

Individual checks are available through `make lint`, `make test`, `make test-browser`,
`make security`, `make docs` and `make build`. Provider credentials are unnecessary
for offline engineering tests.

## Browser and native tests

Provision Chromium with `verboisy setup`. Linux hosts also need the
browser's operating-system libraries. Browser tests must exercise the actual
configured sandbox; a permissive isolated test environment does not establish
production sandbox behavior.

Optional C++ tests build the native modules and verify equivalence with Python
reference paths. See [native execution](native.md) for compiler and interpreter
contracts. Ordinary installation retains the Python implementation.

## Provider evaluation

The opt-in evaluator runs annotated synthetic cases with the configured model:

```bash
python scripts/evaluate.py --live --repetitions 3 \
  --mode evidence baseline --output evaluation-results/model-evaluation.json
```

It can incur provider charges. Synthetic-case success is distinct from internet
research quality. [Evaluation](evaluation.md) describes finite-source annotation,
precision, recall, completion correctness and cost measurements.


## Complete local gates and evidence limits

Run `poetry check --lock`, `poetry install`, Ruff lint/format checks, `mypy src`, and
the offline statement/branch coverage gate at its unchanged 100% threshold. Build both
native modules and run `scripts/check_native_tests.py`.

Provision Chromium explicitly; Linux may need administrator-installed OS libraries
via `python -m playwright install --with-deps chromium`. Run
`VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m "browser and not live" -v` with the required sandbox.
Use an intact browser distribution and the sandbox configuration required by the deployment.

Run `poetry run pip-audit --local`, strict MkDocs, `poetry build`,
`python scripts/check_distribution.py --dist-dir dist --from-sdist --install-smoke`,
and `python scripts/check_repository.py --json`. The package is a local
audit skip when not indexed; record dependency scope/skips separately. The checker
covers all public Markdown and local anchors/HTML; Material renders Mermaid containers.

Release evidence binds each result to its source, configuration and environment.
Report files are excluded from source fingerprints. The release review considers
engineering checks, annotated research, platform and Docker results, browser policy,
scale and recovery evidence, and independent review.

Native sanitizers, complete workloads and filesystem or power-loss tests are required
where the delivered profile makes those claims. Record the exact infrastructure,
measured limits and reviewer for each result. Subsequent changes require the affected
checks and source-bound approvals to be renewed.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
