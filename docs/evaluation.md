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
records the current source hashes, executed gates and explicit limitations.
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

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
