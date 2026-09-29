# Migrating from 0.1 to 0.2

This is an architectural replacement and a release candidate, not a compatible internal
patch. Keep the repository private until the release gates pass. Use the delivery's
`apply.py` on a new Git branch: preview first, then apply. It backs up every overwritten
or deleted managed file, preserves Git history and unrelated files, and does not touch
`.env`. It does not fetch or merge your private repository. Review its diff against your
actual checkout, which may contain changes absent from the supplied snapshots.

The old `Agent`, `Planner`, raw-record extraction engine and model-generated action loop
are removed. Public `verboisy run`, `run()` and `arun()` now use one evidence-backed engine.
Custom integrations using the old internal classes require changes; see the API reference.

Use a **new SQLite file**. Legacy data remains historical evidence and is not automatically
promoted to verified data. This candidate uses research database version 2 and refuses
other versions. Preserve both the original database and its relevant logs.

`--max-steps` now limits page visits per invocation; task page/depth/interaction limits
persist. Model accounting persists across resume. `MODEL_REQUEST_BUDGET` limits conservative
request units (UTF-8 message bytes plus maximum output tokens per attempt), not billing.
`MAX_TOTAL_TOKENS` remains a fallback setting, with this request-unit meaning. Actual
provider-reported token usage is recorded separately. Resume cannot change schema or task.

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
