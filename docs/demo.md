<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Demonstrations and evaluations

A useful demonstration starts with a real information need, authorized sources and
an explicit output contract. It should show how records are accepted, how evidence
is inspected and what happens when the data cannot meet the requested requirements.

## Request a guided demo

Email [emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com) with the
workflow, source types, target schema and approximate volume. Use shareable examples;
do not include confidential inputs or credentials. Hands-on evaluations require
separate written permission. See [commercial enquiries](commercial.md).

## Demonstration outline

1. Define the question or input dataset and the permitted sources.
2. Choose columns or JSON Schema, identity and relevant comparison requirements.
3. Show accepted output alongside the evidence and rejected or incomplete cases.
4. Inspect a saved proposal and explain the accept/decline resume paths.
5. Demonstrate recovery and export lineage without resetting expenditure.
6. Record elapsed time, useful output and actual billed cost where available.

Label deterministic fixtures, local processing and real model calls accurately.
Do not present an offline stub or a benchmark as a live-web quality demonstration.

## Evaluation tooling

`scripts/evaluate.py` supports an opt-in model-based comparison across fixed source
layouts and schemas. It records exact-match results, accepted records, reported
tokens, request units and elapsed time. Negative controls include absent websites
and mixed entities. It requires approved credentials and an explicit spending limit.

The baseline receives the same captured evidence and schema prompt. This controls
source availability but does not compare every browser-enabled assistant or every
site class. Held-out real-task evaluation is described in
[acceptance methodology](production-acceptance.md); browser integration remains a
separate engineering check.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
