<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering notes

These notes explain the invariants behind Verboisy's implementation. They complement
[architecture](architecture.md) and the behavior-oriented technical references.
Version changes are recorded in the
[changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md).

## Separate proposals from accepted data

Models propose observations and interpretations. Candidate admission independently
checks schema shape, source bindings, observed quotes and entity scope. Semantic
review cannot replace deterministic grounding. A model-generated completion signal
cannot bypass the runner's declared dataset requirements.

Provider execution is isolated from acceptance. Explicit profiles determine model
parameters and credential routing, while request reservations and usage journals
preserve expenditure across errors and resume. Search results locate possible
sources; snippets are not accepted as final record evidence.

## Replay the original observation

Accepted candidates, snapshots and selected records must belong to the same run.
Replay checks saved identity, exact snapshot payload and ownership before comparison,
admission or export. A missing or foreign page stops the operation rather than
silently attaching evidence from another run.

Source assets preserve acquired bytes, hashes, row order and source locations.
Strict decoders reject repeated JSON keys and non-finite values instead of repairing
saved observations. Supported historical representations retain their values and
optional-field omissions. A valid hash establishes byte consistency, not truth.

## Keep transformations inspectable

Projections, numeric display, units, descriptors and reference periods remain linked
to grounded source bindings. Output lineage maps public rows to internal evidence
identities. Grouped outputs include all contributing records, and cell lineage
explains the supported derivation or reports that it remains unresolved.

Changing presentation never rewrites raw evidence. Arithmetic requires compatible,
observed units. Ranges remain ranges; no parser or display layer invents an upper
bound, gender-specific measurement or unsupported conversion.

## Validate recovery before state changes

Resume preflights saved schemas, tasks, product options, output destinations,
presentation entries, discovery journals and relevant rejected-candidate evidence.
A malformed saved value must fail before a requirement decision or new research
request can change state. Explicit overrides do not conceal corrupt stored inputs.

Requirement-history replay checks each proposal and decision against its baseline.
An accepted decision must leave the proposed requirements; a declined decision must
retain the prior requirements. Equivalent declined offers are not repeatedly raised.
Recovery preserves journals and budgets rather than resetting them for a fresh run.

## Bound caches and isolate returned values

Compiled schema and source-replay caches are bounded and scoped to their invocation.
Each distinct snapshot can be decoded once within an operation without skipping
ownership or per-candidate checks. Independent copies keep returned models and
writer-owned payloads from changing future replay results.

Publication occurs only after the relevant durable write succeeds. A failed journal
write must not expose a successful cache entry. The next independent operation reads
the ledger again, including mutations introduced after an earlier failure.

## Treat scale as a separate contract

The regular research API returns accepted records in memory. Large local preparation
uses a separate streaming ledger, immutable chunks, bounded record buffers and cursor
paging. Rows and committed progress advance in one transaction. Interruption recovery
uses the retained source capture instead of assuming the original file still exists.

Scale measurements are tied to a workload, runtime and version. Benchmarks collect
CPU, wall-time and allocation measurements alongside output digests. Comparison
reports suppress ratios when environment or correctness contracts differ.

## Keep native execution narrow

Optional C++17 components implement selected evidence matching and Unicode-boundary
workloads. Python owns policy, provider execution, persistence and acceptance rules.
Native paths retain Python references and equivalence tests. Normal installation
needs no compiler, and native absence must preserve the supported Python path.

## Maintain readable responsibility boundaries

Modules separate acquisition, contracts, verification, persistence, presentation and
output. Comments explain invariants, failure ordering and decisions that are not
obvious from the statements themselves. Tests focus on observable behavior and
negative controls. Technical documentation records limitations alongside capabilities.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
