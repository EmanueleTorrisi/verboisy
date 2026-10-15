<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Search and recovery

Use source URLs when you know the scope. Otherwise configure `SEARCH_PROVIDER=brave`
and a private `BRAVE_SEARCH_API_KEY`. Brave results seed the queue; snippets are not
facts and search result coverage is not exhaustive. Disabled search rejects URL-free
runs before any model request. Google browser scraping is no longer a production path.

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
