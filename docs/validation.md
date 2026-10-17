<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering validation

The supported development environment uses Python 3.11–3.14 and Poetry. Execution,
including development tests, requires the permissions described in [licensing](licensing.md).

## Standard checks

For the source-bound release report, after `bash scripts/bootstrap.sh`:

```bash
source .venv/bin/activate
python scripts/verify_release.py --native --audit --package
```

This saves executed outcomes and artifact hashes without claiming all seven release
gates are complete. See [release qualification](release.md) for evidence review.
The existing Make targets below remain available to developers using Poetry.

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
native modules and run `scripts/check_native_tests.py`. A threshold failure is a failed
gate, even when behavioral tests pass; do not replace it with a certification claim.

Provision Chromium explicitly; Linux may need administrator-installed OS libraries
via `python -m playwright install --with-deps chromium`. Run
`VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m browser -v` with the required sandbox.
Missing/truncated downloads block browser qualification; do not substitute mocks.

Run `poetry run pip-audit --local`, strict MkDocs, `poetry build`,
`python scripts/check_distribution.py --dist-dir dist --from-sdist --install-smoke`,
and `python scripts/check_repository.py --json`. The package is a local
audit skip when not indexed; record dependency scope/skips separately. The checker
covers all public Markdown and local anchors/HTML; Material renders Mermaid containers.

Current source-bound evidence excludes reports to avoid recursive fingerprints.
Configured CI and historic results are distinct from executed final-source results.
Real providers/annotated research, supported platforms, Docker, sandbox/egress,
million-row resource/durability qualification, native sanitizers/full workloads,
power-loss/filesystems, independent beta, legal and release-owner gates require actual
infrastructure and authorized owners before production acceptance.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
