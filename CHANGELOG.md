<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Changelog

Changes are grouped by product version and technical subsystem. Version identifiers
refer to the corresponding implementation; publication dates are recorded with
release tags rather than inferred from documentation edits.

## 1.0.0

### Acquisition and provider execution

- Route semantic planning, source assessment, extraction and escalation through
  explicit model profiles, isolated credentials and endpoint-specific parameters.
- Reserve model request units before transport; persist reported usage independently
  from conservative reservations. Count search attempts across providers and resume.
- Enforce host and path policy before following browser redirects. Pin dataset
  connections to validated DNS addresses while preserving TLS hostname verification.
- Acquire explicitly granted local files and declared HTTP GET sources with
  origin-scoped headers, response-size limits and immutable byte captures.

### Structured extraction and evidence

- Parse CSV/TSV with unique headers and exact row widths; decode JSON/JSONL with
  duplicate-key, non-finite-number and object-row rejection.
- Support bounded text, DOCX and XLSX adapters without executing formulas, macros
  or embedded content. Preserve arbitrary asset bytes with hash/reference records.
- Apply explicit projections, mappings, reference periods and grounded unit
  conversions. Preserve raw observations independently from displayed values.
- Verify snapshot ownership, observed quotes, entity scope, candidate identity and
  strict stored JSON before admission, comparison, evidence refresh or export.
- Preserve output-to-record and per-cell derivation through sorting, grouping,
  numeric display and re-export; unresolved derivations remain explicitly marked.

### Persistent execution and large local datasets

- Persist research frontiers, candidate decisions, requirement proposals and request
  journals in SQLite. Validate saved contracts before resume changes run state.
- Distinguish declining a requirement proposal with `--resume` from accepting its
  exact saved terms with `--okresume`.
- Provide a separate streaming ledger with immutable chunks, bounded row/byte
  buffers, transactional progress and cursor paging. Resume from captured input
  after interruption or removal of the original source.
- Export streaming rows and evidence as JSONL with source captures and checksums;
  ordinary research retains its materialized record-list API.
- Order declared time series by verified timestamps; diagnose duplicates, gaps and
  ambiguous local clocks without interpolating missing observations.

### Interfaces and portability

- Provide CLI, synchronous/asynchronous research APIs, streaming APIs, safe model
  configuration inspection, saved-run diagnostics and portable evidence readers.
- Add optional C++17 scalar/batch quote matching and Unicode-boundary helpers,
  Python reference paths, native provenance and differential tests.
- Reject OOXML member names changed by ZIP normalization; make UTF-8 fixture/export
  decoding explicit on Windows; bound recovery after hard process termination.
- Validate clock and UTC-offset boundaries consistently across supported Python versions.

### Distribution and documentation

- Declare source-inspection terms and proprietary package metadata. Execution and
  reuse require separate written permission; third-party notices remain independent.
- Provide English documentation and seven README translations, security reporting,
  commercial contact, technical examples and scoped performance measurements.

## 0.2.0rc1

### Evidence engine replacement

- Replace model-directed action/completion and raw extraction with a persistent
  crawl frontier, structured candidates and independent evidence admission.
- Introduce source snapshots, proof bindings, identity conflict quarantine and
  evidence/manifest export sidecars.
- Add browser provisioning, semantic review and durable model request accounting.
- Replace legacy internal agent/planner interfaces and introduce the research ledger.
  See [migration](docs/migration.md) for integration and database boundaries.

## 0.1.0

### Initial research interface

- Establish the goal-and-schema research interface, model/browser orchestration
  and structured extraction/export workflow.
- This historical implementation predates the persistent evidence admission and
  streaming contracts described above.

[Version evolution](docs/development-roadmap.md) connects these milestones to the
current component architecture. Earlier license grants remain governed by the
terms accompanying their versions.
