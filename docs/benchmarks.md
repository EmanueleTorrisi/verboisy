<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# CPU and memory benchmarks

Run from the repository root using the same Poetry environment as the application:

```bash
poetry run python -m benchmarks.runner --rows 1000 --lineage-rows 100 --repeats 3 --output benchmark-results/baseline.json
poetry run python -m benchmarks.runner --rows 10000 --case parse_csv --case parse_json --case parse_jsonl --case group --case sort --repeats 3 --output benchmark-results/large.json
```

The default run covers CSV, JSON and JSONL parsing; evidence verification; grouping;
stable sorting; and scalar and grouped cell lineage. All cases call production code.
Inputs preserve Unicode, quoted newlines and literal formula text. Independent checks
verify parsed values and hashes, sort order, group averages and contributors, and
resolved lineage mappings. A changed output stops the run instead of publishing a
successful report. Checks remain active under `python -O`.

Each invocation prepares synthetic inputs and, for lineage, a temporary SQLite ledger.
It does not read `.env`, open the configured research ledger, navigate a browser, or
request a search or model response. Reports contain runtime versions, dependency and
source-file SHA-256 hashes, fixture digests, sample timings and output digests. No
credentials or research records are included.

## Measurement boundaries

Fixture construction, ledger population, correctness checks and output hashing happen
outside the timing intervals. One untimed invocation warms each case. Each repetition
records process CPU time and monotonic wall time; garbage collection runs before each
sample, and its enabled state is recorded. CPU measurements include work on all threads
in the process. The harness runs cases sequentially in the current process.

Memory uses a separate invocation with `tracemalloc`. `peak_python_bytes` measures
incremental traced Python allocations during that operation. It excludes prebuilt
fixtures and is **not process RSS**; SQLite buffers and other native allocations may
be absent. Timing samples do not run under `tracemalloc` or `cProfile`.

Use a separate profile invocation to locate expensive functions:

```bash
poetry run python -m benchmarks.runner --case lineage_grouped --lineage-rows 100 --profile-dir benchmark-results/profiles --output benchmark-results/profile.json
poetry run python -m pstats benchmark-results/profiles/lineage_grouped.prof
```

Profiles add overhead and must not be compared with unprofiled timings. `pstats` accepts
`sort cumulative`, `stats 20`, and `quit`. The report's timing samples still remain
unprofiled even when profiles are requested.

## Comparing runs

Compare the same case, row count, fixture digest, runtime, dependency versions, machine
and GC state. Keep the machine idle and repeat the experiment. Source hashes identify
which implementation changed. Stable output digests omit generated ledger identities
while retaining values, derivation steps and status; contributor identities are checked
against the ledger on every invocation.

Use `--rows` for parsing, verification, grouping and sorting (1-100,000); use
`--lineage-rows` for lineage (1-2,000). `--repeats` accepts 1-100. Repeat `--case` to
select work. These caps bound fixture counts, not execution time or total memory.
Verification and ledger setup can take substantially longer than parsing.

Synthetic results describe these fixtures, not live research latency or every dataset.
Use representative, appropriately sanitized production inputs in a separate assessment
before selecting an optimization. There is no CI speed threshold: correctness gates
must not depend on noisy machine timings.

## Ordinary ingestion workflow

Measure the complete local JSON workflow, including immutable capture, candidate
admission, result shaping, portable export and text proof:

```bash
poetry run python scripts/benchmark_ingestion.py --counts 50 100 200 400 --repeats 3 > benchmark-results/ingestion.json
```

Each repetition uses a fresh ledger. Fixture creation and final expected-value
checks are untimed. Reports retain imported source hashes, workload hashes, runtime
and dependency versions, wall/CPU samples, median throughput and process lifetime
high-water RSS. RSS includes imports and all cases; it is not incremental memory
per record. Three repetitions do not support reliable tail-latency estimates.
Use the same driver and dependency environment for baseline and patched runs.

Ordinary ingestion validates the accepted collection once at invocation entry.
Admission then reports its committed record-count delta. Inserts increment the
count, conflicts decrement it, and duplicates/replacements preserve it. This avoids
repeatedly decoding the growing collection just to decide whether a target is met.
Final evidence validation and publication retain their existing checks. Other
collection scans and portable serialization still contribute to workflow cost.

## Selecting native work

Identify a repeatable CPU bottleneck before adding C/C++. Investigate repeated database
queries, allocations and algorithmic work first. Network waits and model latency do not
become faster through native code. Some dependencies already execute native routines.
Any later native implementation needs a Python reference, identical output checks,
call-overhead measurements and portable build validation. This harness adds no native
implementation and makes no acceleration claim.

## Compiled record validators

Evidence verification reuses private compiled models for JSON schemas up to 65,536
serialized bytes, retaining at most 64 schema entries in the process. Every record
is still validated; outcomes and records are never cached. Schema changes produce
a new key, field order stays intact, and caller mutations cannot alter a cached
model. Oversized and non-JSON Python inputs use the original builder. Invalid
schemas are never cached as successful compilations. The public `SchemaBuilder`
continues returning fresh models. Restarting the process clears this transient cache.

The warm verification benchmark includes this reuse. Compare with the pre-cache
baseline using matching inputs and output digests; startup compilation remains an
untimed warmup cost rather than disappearing from actual application startup.

## Lineage input reuse

A cell-lineage generation reads accepted evidence and effective records once, then
shares those inputs with grouped contributor replay. Candidate models, raw field
maps, grounded projection bindings and dataset assets are prepared lazily and
reused within that generation. Scalar model replay data is released after each
output row; grouped replay data remains available across contributor cells until
the generation finishes. The contributor chains and unresolved-status rules
remain intact. Presentation-unit discovery may make a separate evidence read.

This is invocation-local reuse, not a global cache or a database transaction. A
subsequent generation reads the ledger again; concurrent ledger changes still
follow the existing store consistency rules. Replay results are discarded after
the call. Output rows, contributor order and the accepted ledger are not mutated.

Compare both scalar and grouped lineage with the retained baseline:

```bash
poetry run python -m benchmarks.runner --case lineage_scalar --case lineage_grouped --lineage-rows 100 --repeats 3 --output benchmark-results/lineage.json
```

Correctness regressions pin both 100-row derivation digests from the pre-reuse
baseline and check bounded ledger reads, no writes, and new evidence on later
exports. Reduced replay work does not establish factual truth about source claims.

## Literal quote matching

The optional `quote_regex`, `quote_python` and `quote_native` workloads compare
eight literal-boundary cases per row. The default workload list remains unchanged.
The verifier uses the portable Python backend unless a shell environment override
selects regex or native. Reports include this selection, quote-fixture hashes and
the native binary hash when it is used. See [Native matching](native.md) for local
builds, Unicode equivalence checks and complete-verifier comparisons.

## Verification rule overhead

Profiling complete verification identifies the cost of its field loop. In the local
10,000-record workload, schema validation remains the largest cumulative cost.
The field loop now constructs at most one default `FieldRule` per verification
call, only when an unspecified field needs one. Explicit rules remain authoritative;
there is no shared mutable default across records. Mapping keys are serialized
only when a rule has a nonempty mapping. Schema, quote, scope, value and identity
checks still run for every record as before.

On the local CPython 3.12 machine, three warmed repetitions reduced median CPU
from about 554 ms to 442 ms (about 1.25 times faster) with identical output digests.
This is a synthetic verifier result, not a promised improvement to network or
model-driven research. Compare the same workload on the target machine:

```bash
poetry run python -m benchmarks.runner --case verify --rows 10000 --repeats 3 --profile-dir benchmark-results/profiles-verifier --output benchmark-results/verify-profile.json
```

Profile files add instrumentation overhead; use the report's unprofiled samples
for timings and the profile to locate costs. Native mode remains optional.

## Compare saved reports

The offline comparison command reads two saved reports; it does not rerun workloads,
read `.env`, open the research ledger, or contact providers:

```bash
poetry run python -m benchmarks.comparison benchmark-results/verify-python.json benchmark-results/verify-profile.json --output benchmark-results/comparison-verifier.json
```

Matching cases must have the same row count, domain, GC state, relevant fixture
hash and checked output digest. Python, platform, machine architecture, SQLite,
dependencies and measurement-method metadata must match. Source hashes and backend
or native binary changes are reported separately because they can be the intended
subject of an experiment. A machine/platform string is not a hardware fingerprint;
run both measurements on the same physical machine under similar conditions.

The command verifies sample counts, nonnegative integer nanosecond counters,
finite medians matching those samples, and traced allocation measurements.
Measurements must fit within the nonnegative signed 64-bit range.
It reports CPU speedup (`before / after`), CPU reduction fraction, wall speedup and
traced Python allocation ratio (`after / before`) only for comparable cases. An
unresolved zero timing suppresses ratios; a zero allocation baseline produces a
null allocation ratio. Repetition counts are shown and may differ. No statistical
significance or general research-speed claim follows from these synthetic samples.

Exit status 0 means all cases are comparable, including slower results. Status 1
means a case is missing or incompatible; the comparison report still explains why.
Status 2 means an invalid report, unsupported version, file error or output path
that would overwrite an input. Duplicate JSON keys and non-finite numbers are
rejected. Input files remain unchanged; `--output` writes a separate atomic JSON
report. Omitting `--output` prints the comparison instead. There is no speed gate.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
