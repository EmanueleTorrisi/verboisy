# Search and browser recovery

`SEARCH_PROVIDER=google` preserves the original browser-search behavior. Google can
reject automated traffic. A detected automated-traffic warning pauses with
`stop_reason=search_unavailable`; it is not an empty successful research result.

## Search configuration

For general web discovery, use the optional Brave Search API:

```dotenv
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=your-private-search-api-key
SEARCH_TIMEOUT_SECONDS=30
```

Obtain the separate search credential from the [Brave dashboard](https://api-dashboard.search.brave.com/).
The model provider key does not authenticate search. Your search plan and quota apply.
The integration uses the [documented web endpoint](https://api-dashboard.search.brave.com/api-reference/web/search/get),
requests at most ten results per query, and does not automatically paginate the API.
Queries must fit 600 characters and 75 words. Empty discovery results do not prove
that the requested companies do not exist.

Search results are saved as discovery links and supplied separately to the planner.
The browser stays on its current page until NAVIGATE. Extraction always reads browser
HTML; it never substitutes API snippets for a source page. Search requests have a total
deadline and a 1 MiB response limit. Missing keys, HTTP errors, malformed responses,
quota failures and timeouts pause the run. The client does not follow redirects,
use environment proxy settings, or fall back to scraped search. Error messages omit
credentials and raw provider error bodies. If `ALLOWED_DOMAINS` is configured, include
`api.search.brave.com` and the intended source hosts.

For a known source, reject SEARCH directly:

```bash
SEARCH_PROVIDER=disabled poetry run verboisy run \
  --goal "Open https://www.ycombinator.com/companies directly. Use visible filters and company profiles to find AI startups explicitly identified as Fall 2026 or F26. Extract only page-supported facts. Do not substitute another batch." \
  --schema examples/yc_startups/schema.json \
  --export yc.json
```

This setting enforces rejection of SEARCH at dispatch. It is not a hostname firewall
for NAVIGATE. Use `ALLOWED_DOMAINS` for destination restrictions, including necessary
asset hosts. A direct-directory run cannot verify general search availability.

## Interaction recovery

The run checkpoints `pending_action` before dispatch: step, action, selector and
starting URL, without typed text or model reasoning. Successful actions enter history.
Failed CLICK, TYPE, CHECK and SELECT actions retain a sanitized operation stage and
Playwright error type in `action_failures`. The next planning step reads fresh HTML
and receives recent failures. An action can partly execute before timing out, so the
planner must inspect the page before attempting another interaction.

`BROWSER_ACTION_TIMEOUT_MS=10000` limits each interaction operation. TYPE can perform
one fill and one submit operation. `MAX_ACTION_FAILURES=3` pauses at the third failed
interaction per invocation, even with successful actions in between. Failed attempts
also consume steps. Resume renews the allowances but retains the last ten failures
and any interrupted intent. It reopens the saved URL; cookies, tabs, scroll position
and SPA state are not restored.

The planner receives input labels, native option values, role controls and selectors
from observed HTML. Locators must match exactly one element. Playwright still checks
visibility and actionability; no force click is used. Native CHECK sets the requested
checkbox/radio state idempotently, and SELECT chooses an observed native option value.
Custom widgets still use visible clicks. HTML attributes are snapshots and may differ
from live control properties.

## Inspect a stopped run

Substitute your database path and full run ID:

```bash
python3 - /absolute/path/yc.db RUN_ID <<'PY'
import json, sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True) as db:
    row = db.execute("SELECT state_json FROM runs WHERE run_id=?", (sys.argv[2],)).fetchone()
    if row is None:
        raise SystemExit("Run ID not found")
    state = json.loads(row[0])
    keys = ("run_id", "status", "stop_reason", "current_url", "step_count", "pending_action", "action_failures")
    print(json.dumps({key: state.get(key) for key in keys}, indent=2))
PY
```

Older databases load with empty failure fields. A selector that an older version never
recorded cannot be recovered retrospectively. Unavailable search and action limits
exit 2 and do not export; fatal errors exit 1. Earlier committed records remain in
SQLite. Only a completed run writes the export.

## Acceptance

Offline regressions cover timeout recovery, fresh observations, bounded retries,
interrupted intent, resume, API routing, redaction, invalid and oversized responses,
and redirect rejection. The required Chromium suite exercises dynamic filters and
missing, hidden and ambiguous controls with a scripted model. These tests do not prove
live model accuracy. Execute the public examples with your actual providers, check
source evidence for every row and assess completeness against the live directory.
Do not treat an empty export as successful positive extraction of F26 companies.
