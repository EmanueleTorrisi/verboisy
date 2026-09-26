# Python and command-line API

```python
from verboisy import RunResult, run

result: RunResult = run(
    goal="Open https://ycombinator.com/companies and find AI companies in the F26 batch",
    schema="examples/yc_startups/schema.json",
    export="result.json",
)
print(result.run_id, result.completed, result.records)
```

The schema may be a string path, a Path, or a dictionary. New runs require a nonblank
goal and schema. Resume with `run(resume=True)` or `run(resume="saved-id")`. A saved
goal/schema takes precedence over supplied replacements. An export destination can
be overridden. A completed id can be re-exported without opening a browser.

`run` and `arun` accept keyword-only `goal`, `schema`, `export`, `resume`,
`headless`, `max_steps`, and optional `config: Settings`.
Use `await arun(...)` inside an existing event loop. `headless=None` uses environment
configuration. Step, timeout and request budgets renew per invocation.

| RunResult field | Meaning |
| --- | --- |
| run_id | Stable full id; a unique prefix is accepted for resume |
| records | Every saved record, including any preserved legacy duplicates |
| export_path | Absolute path actually written, or None |
| db_path | Absolute database path |
| completed | True only after FINISH and successful collection validation |
| status | COMPLETED or PAUSED for normal returns |
| stop_reason | planner_finished, max_steps, model_budget, run_timeout, action_failures or search_unavailable |

Errors raise `VerboisyError` (or configuration validation errors); async cancellation
propagates after cleanup. Durable saved rows remain available. The command line
uses exit 0 for completion, 1 for errors, 2 for paused runs or argument syntax,
and 130 for Ctrl-C.

```bash
verboisy run --goal "Read a public directory" --schema examples/yc_startups/schema.json
verboisy run --resume
verboisy run --resume saved-id --export result.csv
verboisy run --help
```

Resume restores the last saved URL, not a complete browser session. JSON Schema validates
data shape, not factual truth. See the README for configuration and limitations.

Failed attempts and pending intent are saved in `state_json`, separately from successful
action history. Resume provides them to the planner. See [search and recovery](search-and-recovery.md).
