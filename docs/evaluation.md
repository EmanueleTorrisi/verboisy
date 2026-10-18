<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Evaluation and measurement

Verboisy separates execution correctness, evidence support and task usefulness.
A valid schema and passing test suite establish specific engineering properties;
they do not establish the truth or completeness of an arbitrary research result.

## Engineering checks

Offline regressions exercise malformed inputs, source scope, observed quote checks,
snapshot ownership, identity, journal durability, proposal decisions, interruption
and export lineage. Real browser tests exercise rendered acquisition and redirect
policy. Native tests compare optional C++ paths with Python reference behavior.

Synthetic fixtures isolate known inputs and expected behavior. They are small by
design and are not product demonstrations. Streaming workloads generate large inputs
outside the source tree; raw gigabyte files are not committed as fixtures.

Saved reports under `evals/results` retain their original measurements. Reports
marked `historical_report_not_current_patch_qualification` do not qualify the
current source, even when their original tests passed. The export-integrity report
retains its original source hashes, executed checks and limitations.
Verification applies only to the source and environment named by each report.

## Research quality

Evaluate a declared question against independently annotated sources. Preserve the
schema, source scope, model profile, version and request limits with the result.
Useful measurements include:

| Measurement | Interpretation |
| --- | --- |
| Supported-field precision | Accepted non-null claims supported by the annotated evidence |
| Record recall | Expected records recovered from a finite, reviewed source set |
| Completion correctness | Claimed completion agrees with the declared contract and reviewed source coverage |
| Rejection and conflict rate | Observations excluded or quarantined, with reasons |
| Latency and cost | End-to-end time and actual provider billing, including failed work |

Web-wide absence cannot be inferred from a failed crawl or a column containing nulls.
Search results identify possible sources; a snippet does not replace observed record
proof. Review source permissions, sampling bias, missingness and temporal drift for
scientific, training-data and regulated applications.

## Scale measurements

The [recorded streaming workload](streaming.md#recorded-scale-workload) describes
one Linux/Python 3.12 JSONL preparation and export run, including interruption recovery
and byte/evidence checks. It does not measure model-based web research or promise
universal throughput. [Benchmarks](benchmarks.md) document workload hashes, runtime
conditions, timing and comparable output contracts.

The [large-data example](examples.md#large-local-observation-pipeline) generates
separate synthetic input, exercises bounded preparation and demonstrates resume and
paging. Report generated input size, retained ledger size, output size, elapsed time
and process memory separately. Avoid presenting generated observations as retrieved
real-world facts.


## Source-specific engineering evidence

The original export-integrity and offline reports are historical and retain their
original measurements. New `engineering-*.json` reports record the exact source digest,
commands, exit codes, platform and limitations of the new verifier. Report files are
excluded from the digest to avoid recursion. Their
`qualification_applies_to_current_source` is false because an engineering report
alone does not qualify the complete product.

Synthetic fixtures and offline coverage do not replace annotated research acceptance,
live role-profile cost/latency campaigns, real Chromium target/sandbox/egress tests,
Docker and supported-platform runs, durability qualification or release-owner review.
Each gate must have its own executed record before a production claim.

## The 69-run acceptance campaign

The [release matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json)
defines twelve held-out tasks in six workflow classes: tables, profiles, pagination,
rendered pages, CSV and JSON/JSONL. Select permitted sources and independently
annotate expected values before using results to tune behavior.

| Group | Cases | Repetitions | Runs |
| --- | ---: | ---: | ---: |
| Positive held-out tasks | 12 | 3 | 36 |
| Historical regressions | 3 | 3 | 9 |
| Critical controls | 8 | 3 | 24 |
| **Full campaign** | **23** | **3** | **69** |

First review a pilot of three held-out tasks from three workflow classes, one run
each. Run the full campaign only after pilot approval. Baseline comparisons are
additional runs with a separate approved budget. The existing synthetic evaluator
is not an automated harness for this end-to-end campaign.

Retain each run's source digest, goal, schema, task contract, source URLs and hashes,
provider role/profile, request limits, accepted/rejected values, completion status,
output evidence, elapsed time and billed cost. Keep failures and empty runs in the
denominator. Record model billing separately from request units, which are not currency.

## Release acceptance criteria

| Measurement | Target | Meaning |
| --- | ---: | --- |
| Supported-field precision | ≥ 0.99 | Supported accepted non-null claims / accepted non-null claims |
| Finite-source record recall | ≥ 0.95 | Recovered expected records / independently annotated expected records |
| Positive-run success | ≥ 0.90 | Successful positive runs / attempted positive runs |
| Critical-control failures | 0 | Positive results cannot compensate for a critical failure |
| False completions | 0 | Claimed completion must agree with reviewed requirements |
| Positive web run cost | ≤ EUR 2.00 | Actual billed cost, including unsuccessful work |
| Cost per supported output row | ≤ EUR 0.10 | Retain zero-row spend; agree how it is aggregated |
| Median / p95 positive web latency | ≤ 180 / 600 seconds | End-to-end time for the approved profile |

The reference profile covers at most 25 expected records and 25 visited pages.
The approved matrix is authoritative for the released profile and its thresholds;
linked reports record the measured outcomes. Establish the profile and aggregate EUR
budget with `python scripts/release_matrix.py configure-plan` before execution.
That planning command makes no provider calls. Source selection, independent
annotation, semantic scoring and invoice reconciliation have named reviewers.

For cost comparisons, use the same source set, requested output, model profile and
quality threshold. Include retries, failed and empty runs, source acquisition and
review time. Report provider billing separately from compute and human effort.
Deterministic processing avoids model-token charges for those operations; a
percentage saving for an entire task requires a matched, measured baseline.

Critical controls cover absent homepages, hostile page text, mixed entities, missing
range endpoints, unknown methodology, blocked redirects, exhausted budgets and
interrupted export/resume. Qualify every advertised source/format/provider combination
or narrow the advertised scope explicitly.

## Terminal execution

After activating the repository environment:

```bash
python scripts/verify_release.py --native --audit --package
```

Only after paid execution is approved, fixed synthetic snippets can be evaluated
with the chosen authorized model profile:

```bash
read -r -p "Approved model identifier: " VERBOISY_MODEL
python scripts/evaluate.py --live --model "$VERBOISY_MODEL" --repetitions 3 \
  --mode evidence --output evaluation-results/synthetic-model-evaluation.json
```

This can incur charges and does not enforce an aggregate EUR cap. Use provider-side
controls and monitor billing. It does not run real browser acquisition or the 69-run
held-out campaign. An optional baseline adds separately budgeted work.

Use the CLI or research-catalogue example with reviewed real-source contracts for
acceptance runs, preserving each run separately. Current scale, filesystem and
power-loss claims require their own workloads. See [release qualification](release.md)
to save actual evidence and record each reviewed gate; editing statuses alone is
not completion.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
