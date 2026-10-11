<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Finite production release plan

The release target is general-purpose evidence-backed research across domains,
with clear support boundaries and measured product outcomes. Patch letters are
engineering history, not a measure of release readiness.

The canonical contract and evaluation protocol is [Production acceptance](production-acceptance.md).
The machine-readable inventory is `evals/release-matrix.json`. Its pending fields
are deliberate: unselected sources and unrun evaluations cannot count as passes.

| Gate | Required result | Current status |
| --- | --- | --- |
| 1. Contract | Reviewed scope, acceptance matrix, numerical targets and approved evaluation budget | Draft for review |
| 2. Real acceptance | Human-reviewed held-out results with quality, completion, cost and latency evidence | Not started |
| 3. Product experience | Demonstrated failures fixed; usable onboarding, research, proposals, recovery and exports | Awaiting acceptance findings |
| 4. Release reliability | Exact-commit security, platform, native, browser, package, container and recovery evidence | Tooling exists; release verification pending |
| 5. Repository and legal | Consistent metadata, professional comments, README/translations, architecture, policies and licensing | Materials exist; final review pending |
| 6. Independent beta | Intended users complete representative tasks without developer intervention | Not started |
| 7. Release | Frozen artifacts, documented go/no-go, verified distribution, support and commercial demonstration | Blocked by earlier gates |

## Six consolidated implementation batches

The expanded product requires explicit delivery outcomes. These six batches replace
an open-ended patch-letter sequence; they do not replace the seven release gates.
Each batch includes implementation, meaningful regression tests, documentation and
compatibility checks. Final product qualification follows the completed batches.
Only demonstrated defects reopen a batch; optional refinements enter the backlog.

| Batch | Concrete delivery outcome | Completion evidence | Status |
| --- | --- | --- | --- |
| 1. Provider contracts | Model-prefix profiles, isolated credentials/endpoints, explicit JSON and token parameters, role routing and shared budgets | Offline transport contracts, safe inspection, legacy regressions; live certification remains Gate 2 | Implemented; live qualification pending |
| 2. Source modes | Explicit local-file grants and origin-authenticated HTTP datasets; stable capture/replay; source mode separate from model execution | Local CLI/API and portable replay tests; real HTTP origin isolation; deterministic local workflow makes no model/search/browser calls | Core adapters implemented; service qualification pending |
| 3. File and asset workflows | Capability registry, deterministic parsers, binary asset manifests and format-specific extraction adapters | Accepted/rejected fixtures for eight declared modes; local API and HTTP capture, hashes, locators, portable export/replay and safe rejection | Core adapters implemented; product qualification pending |
| 4. Scale | Disk-backed local CSV/TSV/JSONL/text/asset preparation, bounded row buffers, capture/checkpoints, cursor paging and portable streaming exports | Million-row/gigabyte benchmark, interruption/disk-limit/corruption tests, measured RSS/throughput and explicit evidence verification | Implemented; measured Linux JSONL workload passed; wider qualification pending |
| 5. Research semantics and experience | Time-series ordering/timezones/gaps, ranges, units/dates, useful proposals and explicit limitations | Cross-domain held-out cases and historical regressions; accurate proposals and recovery without silent contract changes | Implemented; offline regressions passed; held-out qualification pending |
| 6. Release finish | Consistent CLI/API UX, comments, README/translations, architecture, package/native/platform checks and commercial policy review | Exact-commit release matrix, professional documentation and reviewed licensing outcome | Candidate materials aligned; final-HEAD and legal qualification pending |

Batch 3 treats all file families as potential inputs: structured text, office
documents, columnar/scientific formats, archives, images, audio, video and opaque
binary files. Support has three explicit levels: capture/index only, deterministic
parsing, and model-assisted extraction. Preserving a file with a hash is not a
claim that its contents have been understood. The capability registry must report
the supported level and produce a useful outcome for unsupported extraction.
Archives need bounded expansion; external references and executable content must
not be followed merely because they are embedded in a file.

Batch 3 freezes its initial eight declared modes and fixture inventory in the
release matrix: CSV, JSON, JSONL, TSV, text, DOCX, XLSX and arbitrary asset capture.
The exact parsing and capture boundaries are documented in [File capabilities](formats.md). New niche formats can use an adapter contract
without adding unbounded requirements to the first release. Similarly, provider
compatibility requires an explicit qualification profile; an arbitrary future
API cannot be certified by a generic compatibility claim.

The initial source adapters are explicit files and HTTP GET datasets. Database
drivers, API-specific pagination, interactive login and OAuth flows require
connector-specific contracts and fixtures. These are extension adapters, not
implicit capabilities of an HTTP source declaration. Advertised enterprise
connectors must be selected before their release qualification can be measured.

The acceptance phase includes format/source/provider combinations, correctness,
scale, economics, independent beta and final release verification. Passing unit
coverage closes none of those measured product requirements by itself. The paid
campaign budget is still unapproved; scope approval and successful patch checks do
not authorize spending.

Every release change must name its gate, demonstrated defect or unmet criterion,
validation and expected product outcome. New speculative refactors and language
percentage goals do not extend this release scope. A critical defect can reopen
an affected gate, with a concrete recorded reason. Optional refinements belong
in the post-release backlog.

Retain useful C++ with reference equivalence, platform tests and benchmarks.
Ordinary installation must continue to work without a compiler. Comment review
covers existing files and explains invariants, ownership and recovery; it does
not require narration of every line.

Keep the project private while commercial licensing and third-party obligations
remain unresolved. The current BSD-2-Clause metadata is not changed by this plan.
External code contributions remain outside the sole-maintainer policy.

Prior engineering work is retained in [Engineering history](engineering-history.md).

The scaled API returns counts and paged records rather than the ordinary research
API's materialized list. See [Large local datasets](streaming.md) for supported
formats, recovery, portable bundle version and resource ceilings. Large HTTP
connectors, semantic/entity deduplication and out-of-core sorting/aggregation are
not implicit capabilities of this local preparation path.
