<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Large local observation pipeline

This example generates distinct, timestamped station observations and processes them
through Verboisy's disk-backed streaming API. Records carry a synthetic-data marker;
metadata padding exercises record width. No measurements are presented as real.

The workflow demonstrates source capture, strict JSONL/schema validation, transactional
row admission, bounded invocation progress, resume, JSONL export and cursor paging.
It does not call models, search providers or a browser. It does not claim internet
research at gigabyte scale or apply the ordinary materialized time-series processor
to an out-of-core dataset.

## Small verification run

```bash
python examples/streaming_observations/generate.py \
  --output example-runs/observations/input.jsonl --rows 1000 --metadata-bytes 128
python examples/streaming_observations/prepare.py \
  --source example-runs/observations/input.jsonl \
  --database example-runs/observations/stream.db --rows-per-invocation 500
```

Generation uses bounded memory, prints byte count and SHA-256, and refuses to replace
an existing input file. Preparation prints the saved job ID, cumulative row count,
status, source hash and at most five committed rows.

Use that actual job ID to resume and export:

```bash
python examples/streaming_observations/prepare.py \
  --database example-runs/observations/stream.db --resume JOB_ID \
  --export example-runs/observations/output.jsonl
```

Resume uses captured bytes and the stored schema/limits. It does not need to recreate
or silently change the original source. The export includes per-row evidence and
source capture; output size is distinct from input and ledger size.

## Multi-gigabyte workload

Use a new input/output directory with adequate disk space. Two million observations
with 1,024 padding bytes per record exceed two gigabytes of uncompressed input.
The generator prints the actual size. Allow roughly 25 GiB of available disk space
for source, retained ledger, export and staging; actual requirements depend on data.

```bash
python examples/streaming_observations/generate.py \
  --output example-runs/observations-large/input.jsonl \
  --rows 2000000 --metadata-bytes 1024
python examples/streaming_observations/prepare.py \
  --source example-runs/observations-large/input.jsonl \
  --database example-runs/observations-large/stream.db --rows-per-invocation 250000
```

Continue with `--resume JOB_ID` until the saved job completes, adding `--export` for
the desired output. Default streaming ceilings are 8 GiB captured input, ten million
rows, 1 MiB per record and a 16 GiB ledger. Limits are admission boundaries, not
preallocated capacity or performance promises.

## Integrate paged results

```python
from contextlib import closing
from pathlib import Path
from verboisy import StreamLedger

with closing(StreamLedger(Path("example-runs/observations-large/stream.db"))) as ledger:
    cursor = 0
    while page := ledger.page("JOB_ID", after=cursor, limit=1000):
        for entry in page:
            consume(entry["record"])  # Supply the downstream consumer.
        cursor = page[-1]["ordinal"]
```

Keep downstream buffers bounded as well. Sorting, semantic deduplication and large
remote acquisition require their own contracts. See [streaming](../../docs/streaming.md)
and [recorded measurements](../../docs/benchmarks.md).


## Pause and capture-based recovery

An invocation budget prints result JSON/job ID and exits 2 while paused. This is an
incomplete outcome. Explicitly resume the printed job ID; completed capture permits
the original file to be removed. Public samples use verified bounded paging.

Completion/export checks cover rows, evidence and hashes. JSON-mode stream CSV has
JSON headers/cells, distinct from ordinary literal headers. Streaming source IDs are
preserved. Historical timings are source-specific; current resource/throughput and
operational qualification must be measured independently.
