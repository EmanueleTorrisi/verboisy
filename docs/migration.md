<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Ledger and output compatibility

## Current ledger and output compatibility

Back up and verify a ledger before changing execution environments. Ordinary v2/v3
ledgers with supported complete core schemas upgrade atomically to v4. Foreign,
partial and final-symlink databases are rejected before schema/journal mutations.
Streaming remains version 1; invalid contracts/checkpoints are never silently repaired.

Legacy ordinary selected records containing top-level source `id` fail with guidance
to create a new explicitly projected `source_id` run. Captured raw evidence remains.
Optional absence stays absent; typed grouping separates Python-equal JSON categories
and unknown-only aggregates become null. SmartID reference mode/hash bindings are
verified; changed references require a new reviewed run. Invocation pause exits 2.
The following section describes the historical 0.1-to-0.2 transition.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)

## Historical 0.1-to-0.2 transition

This guide describes the architectural transition from the historical 0.1 API.
Back up databases and retained evidence before upgrading, and review the release
notes for the target version. Test custom integrations against a copy of the ledger
before changing a production installation.

The old `Agent`, `Planner`, raw-record extraction engine and model-generated action loop
are removed. Public `verboisy run`, `run()` and `arun()` now use one evidence-backed engine.
Custom integrations using the old internal classes require changes; see the API reference.

Use a **new SQLite file**. Legacy data remains historical evidence and is not automatically
promoted to verified data. The current ledger uses version 4. Writable opening migrates supported older
ledgers; read-only inspection requires the current version. See the
[CLI reference](cli.md) for inspection and recovery commands. Preserve both the original database and its relevant logs.

`--max-steps` now limits page visits per invocation; task page/depth/interaction limits
persist. Model accounting persists across resume. `MODEL_REQUEST_BUDGET` limits conservative
request units (UTF-8 message bytes plus maximum output tokens per attempt), not billing.
`MAX_TOTAL_TOKENS` remains a fallback setting, with this request-unit meaning. Actual
provider-reported token usage is recorded separately. Resume retains the saved requirements unless a supported explicit decision accepts
a proposed change; see [research semantics](research-semantics.md).

A requested count in prose is not an enforceable completion contract: put it in
`task.json` as `target_records`. No explicit target means observed crawl exhaustion is
`EXHAUSTED`, exit 2, for review. A collection schema can impose further requirements.
Failed or paused runs export accepted partial records with an incomplete manifest.

Google HTML search is removed from the research path. Use explicit URLs with
`SEARCH_PROVIDER=disabled`, or Brave Search with your API key. Review the new `.env.example`
against your retained `.env`; do not copy secrets into Git or disable the sandbox.

The first browser use downloads Chromium automatically. Linux native libraries still
require operating-system provisioning. For offline deployments provision the browser
first, then set `BROWSER_AUTO_INSTALL=false`. A missing browser fails explicitly.

CSV defaults to JSON-encoded cells for exact nested/type/null preservation. Choose
`csv_mode: "spreadsheet"` explicitly for conventional spreadsheet cells. All exported data
now has evidence and manifest sidecars. Consumers must check status and file hashes.
