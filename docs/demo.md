# Authentic demonstration and live acceptance

The supplied .cast and docs/demo.gif are illustrative historical material. They are
not evidence of a successful run. The original recording shows 13 saved rows,
interruption, resume and a final 40-row export; the supplied source had no resume
implementation and could not produce that workflow. Do not publish it as a current
verified demonstration.

The fixture below uses a real browser, real configured model, actual validation and
SQLite persistence. It does not fabricate planner output, records, or progress logs.
The HTTP endpoint used in automated tests is explicitly a model stub; do not use that
test as an autonomous-product demo.

## Preparation

From the repository root, complete installation and run the validation commands in
[validation.md](validation.md). Configure .env with the real model credentials, or a
running local Ollama endpoint. API calls can incur provider charges.

```bash
poetry run python scripts/live_demo.py
```

The script serves the supplied two-card directory on an ephemeral loopback port, uses
a fresh uniquely named run directory under demo-runs, pauses after a bounded number
of actions, resumes any incomplete run, and verifies the actual output against the
fixture values. ALLOW_PRIVATE_NETWORK is enabled only in those child processes to
allow the local page. Chromium sandboxing remains enabled unless the operator has
explicitly configured otherwise. A failing or incomplete run returns nonzero.

For the actual public YC workflow, from the repository root:

```bash
poetry run verboisy run \
  --goal "Open https://www.ycombinator.com/companies and find AI startups in the Fall 2026 batch. Use page evidence for batch and category." \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Check the source pages yourself. Record count, batch availability, and model behavior
depend on the live site. No fixed count of 40 is promised.

To verify Ctrl-C recovery, use a fresh database and goal, wait for an actual SAVE log,
press Ctrl-C once, then run `verboisy run --resume` using the same SQLITE_DB_PATH.
Check that the recorded run id is unchanged and saved records persist without new
duplicates. A second interrupt during shutdown or an uncommitted current operation
cannot be promised lossless.

## Record the real terminal

Install asciinema and the agg converter using their official installation guides.
Record only an environment with no visible secrets:

```bash
asciinema rec docs/demo.cast
poetry run python scripts/live_demo.py
exit
agg docs/demo.cast docs/demo.gif
```

These lines are sequential interactive steps: the middle command runs inside the
recording shell, and exit closes that shell. Replay the cast and compare its logs,
run id, actual SQLite rows and export before replacing the README's historical-demo
notice with the new GIF. Retain the generated evidence directory alongside the cast.
Do not edit console output to invent records or hide a failed acceptance check.

A replacement live recording was not produced in the audit environment: no provider
credentials were supplied, and Chromium downloads failed there.
