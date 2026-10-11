<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering validation

The supported development environment uses Python 3.11–3.14 and Poetry. Execution,
including development tests, requires the permissions described in [licensing](licensing.md).

## Standard checks

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

Provision Chromium with `poetry run verboisy setup`. Linux hosts also need the
browser's operating-system libraries. Browser tests must exercise the actual
configured sandbox; a permissive isolated test environment does not establish
production sandbox behavior.

Optional C++ tests build the native modules and verify equivalence with Python
reference paths. See [native execution](native.md) for compiler and interpreter
contracts. Ordinary installation retains the Python implementation.

## Provider evaluation

The opt-in evaluator runs annotated synthetic cases with the configured model:

```bash
poetry run python scripts/evaluate.py --live --repetitions 3 \
  --mode evidence baseline --output evaluation-results/model-evaluation.json
```

It can incur provider charges. Synthetic-case success is distinct from internet
research quality. [Evaluation](evaluation.md) describes finite-source annotation,
precision, recall, completion correctness and cost measurements.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
