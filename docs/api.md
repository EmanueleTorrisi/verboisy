<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Python API

```python
from verboisy import run
from verboisy.utils.config import Settings

result = run(
    goal="Extract the listed product SKUs and USD unit prices",
    schema="my-schema.json",
    task="my-task.json",
    export="dataset.json",
    max_steps=40,
    config=Settings(sqlite_db_path="research.db"),
)
print(result.status, result.stop_reason, result.manifest_path)
```

Async applications use `await verboisy.arun(...)`; do not call `run` inside a running
event loop. Schema and task may be dictionaries or file paths. Task may also be a
`verboisy.evidence.models.TaskSpec` instance. Records preserve requested property names.

`RunResult` contains `run_id`, `records`, `export_path`, `db_path`, `completed`, `status`,
`stop_reason`, and `manifest_path`. A false `completed` does not discard accepted data.
Failure outcomes after run creation are persisted and returned; invalid input, database
setup errors and export failures raise `VerboisyError` or an OS error. CLI maps failed
runs to exit 1, partial/exhausted to 2, interruption to 130.

`run(resume="FULL-RUN-ID", export="dataset.csv", config=...)` uses the saved contract.
Bare CLI `--resume` or Python `resume=True` selects the latest incomplete research run.
Completed records can be re-exported without starting a browser or calling a model.
Internal 0.1 `Agent`, `Planner`, raw `ExtractionEngine` and `DatabaseManager` APIs are
retired; importing them is intentionally unsupported in this breaking revision.


## Resolved input and output contracts

New research contracts are validated before opening saved state. `maxrows` must be
a non-Boolean integer in 1..100000; task overrides undergo full validation. Identity
fields are 1..20 unique scalar RFC 6901 pointers, including when supplied in a task.
`proof=True` requires an export. Explicit Boolean options and sort declarations are
validated without raw Python type/key errors.

Top-level ordinary `id` is generated metadata; project a source ID to `source_id`.
Nested IDs and independent streaming source IDs remain valid. Default unshaped
output retains optional absence and explicit null; transformations may intentionally
change the output schema, which the manifest reports.

Resume validates saved requirements before proposal decisions. SmartID binds source
and adjacent manifest hashes; changed references require a new reviewed run. JSON
configuration files use bounded regular-file reads with strict finite unique UTF-8 JSON.

---

[Overview](index.md) · [CLI](cli.md) · [Licensing](licensing.md)
