<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Changelog

This file records notable product and compatibility changes. Entries marked
**Unreleased** describe current development and do not identify a published stable
release. Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Research and data preparation

- Add explicit provider profiles, model-role routing and durable request accounting.
- Add granted local inputs and declared HTTP datasets with origin-scoped credentials.
- Add strict deterministic CSV, TSV, JSON, JSONL, text, DOCX and XLSX adapters.
- Add immutable binary asset capture, portable bundles and grounded projections.
- Add separate disk-backed local streaming, paging and interruption recovery.
- Add observed units, descriptors, reference periods, ranges and time-series policies.
- Add reviewable requirement proposals with distinct accept and decline resume paths.
- Preserve row and cell lineage through grouping, sorting and display changes.

### Reliability and developer interfaces

- Provide CLI and synchronous/asynchronous Python APIs with saved-run diagnostics.
- Preserve budgets, evidence ownership and strict JSON replay across resume.
- Enforce redirect scope before fetching excluded browser destinations.
- Add Python/OS CI, real browser integration and optional C++ equivalence checks.
- Reject office archive names altered by platform normalization.
- Cover strict timestamp clock/offset boundaries across Python versions.
- Improve Windows text-encoding fixtures and bounded process-termination recovery.

### Documentation and distribution

- Expand the product README and seven translations with supported workflow examples.
- Document security reporting, enterprise deployment and commercial enquiries.
- Introduce source-inspection terms for this version and align package metadata.
- Preserve independent third-party licenses and earlier grants for historic versions.

Real-task quality, provider compatibility, support scope and deployment suitability
remain evaluated for each release and configuration. See the
[roadmap](docs/development-roadmap.md) and [release checklist](docs/release-checklist.md).

## 0.2.0rc1 — Evidence engine candidate

- Replace unverified extraction and model-directed completion with persistent
  crawling, evidence checks and independently reviewed candidate acceptance.
- Preserve user schemas and introduce proof, provenance and manifest sidecars.
- Quarantine identity conflicts and retain legacy databases without silent rewriting.
- Add browser provisioning, independent semantic review and shared request accounting.
- Introduce breaking internal API and ledger changes; see [migration](docs/migration.md).
