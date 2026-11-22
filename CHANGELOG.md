<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Changelog

Changes are grouped by product version and technical subsystem. Version identifiers
refer to the corresponding implementation; publication dates are recorded with
release tags rather than inferred from documentation edits.


## 2.0.0

Verboisy 2.0.0 is the production release for local dataset preparation and extraction
from declared public sources. It adds repeatable workflows, dataset checks,
verifiable analytical delivery, and tighter recovery contracts.

### Research and acquisition

- Define versioned workflows with a goal, schema, task, and explicit input bindings.
  Validate recipes without acquiring sources with `workflow-check`, optionally pin
  the exact file SHA-256, and carry workflow identity into exports and replay.
- Extract literal text from a selected region or definition list, and extract text
  or signed integer cells from declared visible HTML tables. Bind each value to its
  source, preserve declared nulls for absent metadata, and refuse ambiguous
  layouts and missing required cells.
- Opt in to hosted discovery for metadata tasks restricted to declared HTTPS hosts
  and paths. Persist the selected detail pages and search acquisition across resume;
  an accepted scope change can renew discovery without resetting request history.
- Use an opt-in model catalog to choose eligible models per role based on declared
  capabilities, context limits and estimated cost. Preserve explicit role overrides
  and keep provider credentials separate from hosted discovery credentials.
- Cap OpenAI search tool calls per request and retain provider usage for incomplete
  responses. Report tool entries and billable search counts separately from search
  attempt budgets and invoice totals.
- Reuse verified source assessments in a private, scoped project cache with expiration
  and size limits. Bind reuse to the captured source and resolved request contract.
  Inspect, clear or bypass the cache explicitly.

### Dataset operations and delivery

- Compare completed streaming snapshots by explicit single or compound keys with
  `stream-update`. Export inserts, updates and count summaries; report absent rows as
  unobserved unless both snapshots are declared complete.
- Enforce versioned quality contracts with `stream-quality`: row bounds, minimum
  field completeness, and unique typed keys. Keep failures distinct from execution
  errors with an explicit CLI exit code.
- Publish bounded gzip JSONL and typed Parquet shards with source hashes, row evidence,
  and a manifest. Parquet uses an explicit physical column contract and PyArrow.
- Verify delivered bundles offline with `stream-verify`. Check file digests and proof
  inventories for both formats, and compare decoded data rows and proofs for gzip JSONL.
- Page through verified streaming results with explicit byte and row budgets and a
  stable continuation cursor. Resume from a checked checkpoint without revalidating
  the same captured prefix twice.
- Read versioned operational reports for research or streaming ledgers. Preview
  retention in an owner-private Linux workspace, protect saved IDs, and apply a
  specific unchanged plan by its SHA-256.

### Contract and recovery corrections

- Preserve CSV schema column order across resume and keep the saved source policy on
  navigation and recovery. Align CLI artifact labels and expose the installed version.
- Protect source, configuration, ledger, and SmartID inputs against export aliases
  and recheck publication paths, including symlinks and hardlinks.
- Protect spreadsheet-mode streaming CSV headers and fields that could be interpreted
  as formulas. Preserve original values in evidence and keep a saved JSON CSV mode for
  typed interchange.
- Preserve optional absence, typed grouping, finite aggregates, mixed-value ordering,
  and contributor missingness. Resolve local schema references consistently and reject
  duplicate-key or non-finite model JSON.
- Index SmartID reference matching; preserve typed compound keys and contributor scope.
  Verify reference mode and hashes before execution and reject a changed reference on resume.
- Restore validated `--task` files, align incomplete-run exit codes, preserve unrelated
  ledgers, include browser startup in runner deadlines, and cancel owned provisioning
  processes when setup is interrupted.
- Verify streaming contracts, captures, prefix replay, and pages without altering the
  version 1 ledger. Reject unsupported collection rules before ingestion and publish
  manifests only after their referenced files are in place.

### Runtime and packaging

- Load CLI and Python execution components on demand. Use committed admission deltas
  instead of recounting the collection after every row, and reuse verified JSON during
  streaming replay and proof serialization.
- Optimize ASCII word boundaries and whole-text matching in the optional native engine
  while retaining Unicode behavior and the Python fallback.
- Require Python 3.11.5 or later, through Python 3.14. Refresh the dependency lock and
  validate built archives and installations from both wheel and source distribution.

See the [migration guide](docs/migration.md) for upgrade and replay behavior.

## 1.0.0

### Acquisition and provider execution

- Route semantic planning, source assessment, extraction and escalation through
  explicit model profiles, explicitly routed credentials and endpoint-specific parameters.
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
