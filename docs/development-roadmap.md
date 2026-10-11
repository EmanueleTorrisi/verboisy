<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Version evolution: 0.1.0 to 1.0.0

Verboisy evolved from goal-driven browser extraction into an evidence-backed research
and data preparation system. The milestones below describe architectural changes;
they do not invent releases between documented versions.

| Milestone | Product architecture | Data contract |
| --- | --- | --- |
| 0.1.0 — Initial research interface | Model/browser orchestration, requested fields and structured export | Goal and schema drive extraction |
| 0.2.0rc1 — Evidence engine | Persistent crawling, snapshots, independent candidate admission and identity conflict handling | Records require inspectable source bindings; completion is evaluated independently |
| 1.0.0 — Integrated workflows | Scoped web research, deterministic local/HTTP adapters, separate large-file streaming, proposals, provider profiles and optional C++ | Saved contracts, durable budgets, strict replay and portable row/cell provenance |

## Research and acquisition

The current research engine owns source scope, page capture, candidate admission,
comparability and saved-run recovery. Model profiles configure execution independently
from source permissions. Initial discovery, repair search and extraction share durable
accounting without treating conservative request units as billed tokens.

## Data preparation and scale

Local and HTTP dataset adapters preserve source bytes, hashes, physical locations
and explicit projections. CSV, TSV, JSON, JSONL, text and bounded Office inputs have
format-specific contracts; arbitrary files can be captured and indexed as assets.

Large local processing uses a separate ledger, chunk capture, bounded buffers and
cursor paging. It does not reinterpret ordinary browser research as a streaming
interface or infer database/API connectors from an HTTP declaration. See
[file capabilities](formats.md) and [large local datasets](streaming.md).

## Semantics and output

Ranges, units, reference periods and time series require grounded values and explicit
policies. Requirement proposals expose the exact offered change before acceptance.
Sorting, grouping and presentation retain contributor and per-cell lineage.
Original evidence remains distinct from formatted output.

## Engineering foundations

Python owns policy, interfaces, adapters and persistence. Optional C++17 components
serve measured evidence-matching workloads with reference equivalence and native
tests. Installation retains the Python path without requiring a compiler.

[Architecture](architecture.md) describes responsibilities and trust boundaries.
[Changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)
records subsystem changes. [Evaluation](evaluation.md) explains the meaning and
limits of engineering tests and workload measurements.

## Product direction

The long-term objective is a trusted standard for evidence-backed extraction:
structured data with inspectable origins, controlled execution and reproducible
transformations. Subsequent version changes are recorded in release notes. Feature
requests are welcome through the project's issue tracker.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
