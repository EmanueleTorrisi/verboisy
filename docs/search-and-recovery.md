<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Search and recovery

Use explicit source URLs when the scope is known. For hosted discovery, select
`SEARCH_PROVIDER=brave` or `SEARCH_PROVIDER=openai` and configure the corresponding
credential. Candidate URLs seed the queue; facts come from acquired sources.
`SEARCH_PROVIDER=disabled` requires a declared source.

A SQLite file lock prevents concurrent writers. URL work is checkpointed before
navigation, and candidate plus accepted-record writes use one transaction. Interrupted
active pages are requeued on resume. Failed navigation pages remain failed. Hash deduplication
makes repeated acceptance idempotent. Raw HTML and structured snapshots remain in the
ledger. Old database tables are never silently migrated into verified records.

```bash
SQLITE_DB_PATH=research.db verboisy run --resume RUN_ID --export recovered.json
```

Model requests share pacing, retry policy and accounting across discovery extraction
and semantic review. Request reservations are persisted before model dispatch. Provider
reported tokens are recorded separately. `MODEL_REQUEST_BUDGET` counts conservative
request units: UTF-8 message bytes plus maximum output tokens for every attempt. It is
not a billing guarantee. `MAX_TOTAL_TOKENS` is a legacy alias only when the new budget
is unset. Increase the cumulative budget explicitly to resume after budget exhaustion.

401 errors require corrected credentials. 429 quota/daily exhaustion is not treated as
a useful retry loop. Transient requests use bounded delays. Provider rate limits pause the run;
there is no Retry-After-specific retry scheduler. Requests are not retried forever. Permanent source failures,
unsupported browser controls and missing facts remain visible; changing to another
batch/entity to manufacture a successful result is not a recovery strategy.

Use a new run to change schema, scope, identity policy or task limits. Preserve the old
run as evidence. Do not edit records in SQLite and then label them accepted by the engine.


## Declared HTML extraction

Specify `html_metadata` or `html_table` in the task for deterministic extraction
from the rendered page. Both modes use a closed flat schema, declared identity,
and saved source evidence. They run without a language model.

- **Metadata:** Set a simple region selector and a binding for every field. A
  binding reads visible text from a simple selector or an exact label in a
  selected definition list. A genuinely absent field can become null when
  `on_missing: "null"` and the task and schema permit it. Explicit seeds use
  one record per distinct canonical URL.
- **Tables:** Set a simple table selector, the exact visible headers, a key field,
  and the distinct keys to extract from one seed URL. Fields are literal strings
  or explicitly declared signed integers. Ambiguous headers, unsupported layouts,
  and blank required cells stop the declared acquisition.

For metadata discovery, set `html_metadata_discovery: true`, omit seeds, and
declare one HTTPS host and distinct `include_paths`. The target equals the
number of paths, with one eligible detail page selected per path. Resume reuses
the saved selection. Agreed requirement changes can produce a new selection
inside the saved source policy without resetting the request ledger.

`SEARCH_REQUEST_BUDGET` limits hosted attempts across resume. For OpenAI search,
`OPENAI_SEARCH_MAX_TOOL_CALLS` sets the requested tool limit per call (1–32,
default 4). Diagnostics distinguish tool entries and provider-reported billable
searches; request budgets and invoice costs remain separate.

## Deadline and target boundaries

The runner deadline includes browser startup. Initial discovery uses separately
bounded attempts and first-use setup has its own cancellable provisioning ceiling;
this is not a single end-to-end public API deadline. Cancellation stops the owned
installer process/group and releases its lock.

Single-primary-page acquisition denies unsupported secondary targets. Safe bounded
target-policy notices become visible coverage gaps; they do not justify a clean
exhausted-scope claim. Browser policy is not DNS-pinned dataset transport. Deployment
egress and sandbox behavior need real qualification.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
