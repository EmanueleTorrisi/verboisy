<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Release evidence checklist

The six implementation batches prepare a candidate. They do not close the seven
release gates. Record the tested Git HEAD, platform, Python version, dependency lock,
provider/profile, settings and report hashes for each applicable result.

| Gate | Evidence required before marking complete |
| --- | --- |
| Contract | Reviewed scope, numerical quality/economic targets and paid campaign budget |
| Product acceptance | Independently annotated held-out sources, pilot review, full campaign, negative controls and failures |
| Experience/economics | Intended-user flows, useful proposals/recovery, measured costs/latency and supported completion behavior |
| Reliability | Final-HEAD Python/OS matrix, required browser, native equivalence, package/container/security and interruption evidence |
| Repository/legal | Documentation/editorial and translation review, ownership/licensing decision, third-party obligations and accurate claims |
| Independent beta | Representative users finish tasks without developer intervention; defects triaged and resolved |
| Distribution | Frozen verified artifacts, reviewed go/no-go, installation verification, support and commercial presentation |

## Maintainer execution

```bash
make validate
make repo-check
```

`repo-check` is read-only. It checks repository consistency and reports the saved
production status. A successful repository check does not imply completed product
qualification. `validate` additionally exercises the configured runtime, browser,
audit, strict docs and build commands. Record failures; do not convert a required
check into a skip. Use the native and container checks documented in validation.md
for the corresponding release profiles.

The paid pilot/campaign remains separately authorized. Select sources and independent
gold review before spending. Do not use current user datasets, provider secrets or
private systems as convenient test fixtures without explicit source authorization.

Prepare per-file commits according to the commit policy, then validate the completed
sequence's final HEAD. Rebuild after changes to code, dependencies or packaging. A
release must refer to final artifact hashes, not a mutable branch name or a previous
installer's results. Keep publication flags disabled while a required gate is pending.

## Recorded implementation evidence

Batch 4's measured JSONL workload and Batch 5's offline semantics verification remain
under `evals/results`. They qualify their stated workloads and build snapshots only.
The release matrix still records held-out/provider/beta requirements as unrun. A later
refactor does not retroactively change the hashes or scope of those historical reports.
