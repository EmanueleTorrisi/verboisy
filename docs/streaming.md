<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Large local datasets

`verboisy stream` and `verboisy.stream_dataset` prepare explicit local files using
bounded buffers and a separate disk-backed ledger. Results contain counts, status
and a job ID; they never allocate a list containing every output record.
The ordinary `run`/`arun` research interfaces keep their existing result contract
and bounded dataset adapters. Increasing their input limit does not make them
streaming interfaces.

| Scaled declaration | Interpretation | Limits and exclusions |
| --- | --- | --- |
| `csv` / `tsv` | Exact strings under explicit headers | Unique nonempty headers, exact row widths, at most 1,000 columns, bounded quoted multiline records |
| `jsonl` | Typed object per nonblank physical line | Strict UTF-8/JSON, finite numbers, no duplicate keys, at most 32 nested levels |
| `text` | One `text` record per physical line | UTF-8, line locators retained, no NUL bytes or inferred markup interpretation |
| `asset` | SHA-256 and byte-count index record | Arbitrary bytes are captured, not interpreted |

CSV, TSV and text preserve physical row order. JSONL skips blank lines without
losing physical source locations. Literal formula text is never evaluated.
Row identity is the physical source row: duplicate observations remain distinct.
There is no implicit entity deduplication, semantic review, ordering/grouping,
source discovery, OCR or model extraction in this preparation workflow.

JSON arrays and DOCX/XLSX remain on the bounded adapters described in
[File capabilities](formats.md). Large HTTP acquisition and service-specific
pagination are not implemented by this local streaming interface. A locally
installed LLM does not grant filesystem access; source grants remain independent.

## CLI

Grant the input directory through `DATASET_LOCAL_ROOTS`. Use a dedicated ledger,
not the existing research database:

```bash
verboisy stream \
  --database large-dataset.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

`--schema` takes a JSON Schema file. Object schemas describe one row; an array
schema's object items describe one row while retaining the root reference context.
Omit the schema to preserve any object record. Schema failures stop preparation,
with no silent dropping or coercion. Use `--projection plan.json` for the same
explicit conversion plans supported by ordinary dataset ingestion.

A repeatable batch is not an inferred collection of independent source files.
Each streaming job has one fixed source, format, schema, projection and limits.
Prepare multiple files as separate jobs. A changed schema or source requires a new
job; resume does not silently change the meaning of already accepted records.

To pause after a chosen number of newly committed rows:

```bash
verboisy stream --database large-dataset.db \
  --dataset-file 'csv=/srv/verboisy-inputs/observations.csv' \
  --rows-per-invocation 100000

verboisy stream --database large-dataset.db \
  --resume JOB_ID --export observations.jsonl
```

Use `verboisy stream-status --database large-dataset.db --limit 10`
to inspect recent job IDs and committed counts, including during preparation.
A database with an interrupted SQLite rollback journal may require opening
`StreamLedger` in writer mode once to recover that journal before read-only
inspection can succeed; that recovery does not admit new rows.

Resume uses the saved contract. Do not repeat the source/schema/projection/limit
options. A row budget may pause exactly at the final row; resume then verifies EOF
and marks the job completed. A paused job does not publish the requested export.
Failed jobs exit with code 1 and retain their ID and last committed checkpoint.

## Python and bounded inspection

```python
from contextlib import closing
from pathlib import Path
from verboisy import StreamLedger, StreamLimits, stream_dataset
from verboisy.utils.config import Settings

result = stream_dataset(
    database=Path("large-dataset.db"),
    source=Path("/srv/verboisy-inputs/observations.jsonl"),
    dataset_format="jsonl",
    config=Settings(dataset_local_roots=["/srv/verboisy-inputs"]),
    limits=StreamLimits(max_input_bytes=2_147_483_648),
    export=Path("observations.jsonl"),
)

with closing(StreamLedger(Path("large-dataset.db"), read_only=True)) as ledger:
    page = ledger.page(result.job_id, after=0, limit=100)
    # Continue with after=page[-1]["ordinal"]. The maximum page size is 1,000.
```

Pages use an indexed ordinal cursor instead of increasingly expensive offsets.
Read-only inspection does not acquire the writer lock or change the ledger.
The writer lock allows one preparation/export writer per ledger. Always close
`StreamLedger`; `closing` handles both normal and exceptional paths.

## Capture, checkpoints and recovery

The source is resolved inside explicit directory grants, must be a regular file,
and is checked before and after reading. Authorization protects operator-controlled
files, not a hostile process with the same operating-system permissions.

Capture stores byte chunks of at most 1 MiB, their individual hashes and the final
aggregate SHA-256/byte count. No single multi-gigabyte BLOB or full-file Python
buffer is created. Only a complete, stable capture can admit rows. An interrupted
partial capture has admitted no rows and is reacquired from the original file on
resume; it does not masquerade as an immutable completed asset.

After complete capture, the original file can be removed. Resume and export verify
the saved chunks and aggregate hash. They do not consult the original file or
require its original directory grant again. Resume reparses the captured stream
from its start to reach the checkpoint; its memory is bounded, but repeated small
invocations incur repeated scan time.

Rows commit with their last-processed ordinal in one SQLite transaction. Batches
hold at most 512 records or approximately 8 MiB of encoded row material, plus the
current record. An incomplete batch is discarded. Resume therefore admits neither
duplicated nor skipped rows. A process termination may leave an old `RUNNING`
status; the committed checkpoint determines recoverable progress, not that label.
SQLite/disk failures return a resumable `storage_error` outcome. An operating-system
full disk can prevent a final status write; free space before resuming.

## Resource ceilings

| Default | Ceiling |
| --- | --- |
| Input bytes | 8 GiB |
| Source rows | 10,000,000 |
| Source/projected record bytes | 1 MiB |
| SQLite database pages | 16 GiB per ledger |
| SQLite page cache | 8 MiB; memory-mapped access disabled |

CLI options expose input, row and database limits. Python `StreamLimits` also
controls the record ceiling, which cannot exceed 16 MiB. CSV additionally inherits
Python's field-size guard. A whole record is bounded before multiline CSV parsing
accumulates its fields. Limits are persisted and cannot be enlarged through resume.

The database limit excludes SQLite's temporary rollback journal and export files.
Allow disk space for the captured bytes, row material, portable source and evidence
sidecars. Projections that enlarge records increase storage. A disk-full condition
must not publish an incomplete manifest. Memory and throughput qualification apply
to measured workloads, not every possible schema, format or machine.

## Portable streaming exports

Export formats are JSONL, JSON arrays and flat CSV. JSONL/JSON retain decoded types;
CSV requires stable flat columns. The default `spreadsheet` mode prefixes an
apostrophe to formula-capable string headers and cells, including leading
whitespace and control characters. Numeric values retain their numeric rendering.
CSV empty and null cells both appear empty; the evidence sidecar retains their
distinct source values and the original, unescaped formula text. Nested or changing
CSV columns fail explicitly. No sort or aggregate operation is silently introduced.

For lossless machine-readable CSV, choose `--csv-mode json` on a new job, or pass
`csv_mode="json"` to `stream_dataset`. Every header and cell contains a JSON value;
decode each parsed CSV field with a JSON parser. This preserves nulls, strings and
numbers without exposing formula-leading strings. The mode is part of the saved
contract and cannot change on resume. JSONL and JSON exports remain unchanged.

The bundle contains output rows, an evidence JSONL sidecar, exact source bytes in
`.source.bin`, and a `stream-1` manifest. Evidence maps each output ordinal to a
stable job/physical-row ID, source values and physical line bounds. Projected values
are recorded when they differ; the manifest retains the explicit plan. Consumers
can replay that plan against the preserved source. This is a separate bundle
version; the ordinary `load_portable_assets` reader does not consume it.

Export reparses captured source rows and checks every saved output/source value
and locator before publication. It stages the files, hashes them, then replaces
the manifest last. If replacement fails, a stale manifest is removed so it cannot
certify mixed files. An existing bundle remains untouched during validation/staging.
Source, ledger, configuration and sidecar collisions are rejected, including
symlink targets, aliases through parent directories and hardlinks. The CLI saves
schema/projection paths for resume; Python callers can declare additional input
paths with `protected_inputs=(Path("configuration.json"),)`. Dotenv paths read by
`Settings` are retained automatically. Older jobs retain their known source and
ledger protections, but cannot reconstruct configuration paths absent from their
saved contracts.

The writer requires exclusive control of its output directory. Path and inode
checks do not prevent a hostile process from changing directory entries between
validation and publication. Use private directories with operating-system access
controls for separate writers.
Checksums establish integrity relative to the supplied manifest, not authenticity
or factual truth. Completion means the fixed local preparation contract reached
EOF; it makes no global research completeness claim.

## Recorded scale workload

Run the reproducible Linux benchmark without provider credentials or network calls:

```bash
PYTHONPATH=src python scripts/benchmark_streaming.py \
  --rows 1000000 --padding-bytes 1080 --report streaming-result.json
```

It generates distinct JSONL records exceeding 1 GiB, pauses halfway, deletes the
original source, resumes, exports and independently verifies every output row,
evidence row and file checksum. Temporary inputs, ledger and exports are cleaned
up. The report includes timings, peak process RSS and disk use. Initial acceptance
requires one million rows, one GiB, peak RSS at most 192 MiB, and at least 5,000
rows/second for preparation plus export on the measured environment. Separate
workload/platform reports are required before broader performance claims.

The recorded Linux/Python 3.12.14 result is retained in
`evals/results/streaming-linux-python312.json`, including hashes of the measured
implementation. Its one million rows occupied 1,105,888,890 source bytes. Capture,
admission, resume and export took 130.81 seconds (7,644.72 rows/second); peak process
RSS was 93,478,912 bytes (89.15 MiB). All output/evidence rows and bundle checksums
were independently verified after the original source was deleted. No provider
requests were made. This qualifies that workload; other platforms and workload
distributions still need their own measurements.


## Validated checkpoints and public pages

Array roots permit only `type`, object `items`, `$schema`, `$defs`, `definitions`,
`$id`, `$anchor`, `$dynamicAnchor`, standard descriptive annotations and non-validating
`x-` annotations. Root references, prefix/contains/item-count/uniqueness/unevaluated
assertions and combinators/conditionals fail before a ledger is opened. References
inside items retain the root context. Object roots retain per-row JSON Schema validation.

Saved contracts, types, ceilings and exact ordinal prefixes are verified. Completed
jobs additionally require actual EOF. Resume validates capture and the committed prefix
once before admission, then reuses its positioned parser. Captured bytes permit resume
after source deletion. Corruption fails before status/checkpoint mutation; no implicit
repair or ledger version change occurs.

Public keyset pages return verified source-bound rows from coherent read snapshots.
First access can scan the capture/prefix; subsequent pages at a stable connection
revision reuse at most 32 small stamps. Both own writes and external commits invalidate
stamps; caller transactions remain owned by the caller and are never cached. Pages
are limited to 1..1000 rows, with no full-dataset result list.

Staged export files are flushed/fsynced, directory entries sync where supported, and
the manifest publishes last. Preparation exits 0/2/1/130 for completed/paused/failed/
interrupted outcomes. Status inspection can exit 0 for a paused job. Historical million-row
results apply to their recorded source and host. The [release record](release.md)
identifies qualified resource limits, platforms and recovery behavior. Consult
[validation](validation.md) for the checks used to maintain that scope.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
