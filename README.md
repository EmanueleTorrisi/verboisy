<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="logo.png" alt="Verboisy" width="240" /></p>
<p align="center"><strong>Research with evidence. Prepare datasets with traceable transformations.</strong></p>
<p align="center">CLI · Python API · Local files · Public web · Portable provenance</p>
<p align="center"><strong>1.0.0 development build — production acceptance pending</strong></p>

[Italiano](.github/readme/README.it.md) · [Deutsch](.github/readme/README.de.md) ·
[Français](.github/readme/README.fr.md) · [Español](.github/readme/README.es.md) ·
[日本語](.github/readme/README.ja.md) · [한국어](.github/readme/README.ko.md) ·
[简体中文](.github/readme/README.zh-CN.md)

Verboisy turns a research goal and an explicit data contract into records whose
supporting observations can be inspected. It also prepares declared datasets
without model calls. These workflows share an emphasis on source integrity,
durable recovery and honest completion boundaries.

The repository is maintained privately by Emanuele Torrisi. The implementation
batches are complete; human-reviewed product acceptance, live provider qualification,
independent beta and final commercial/release review remain outstanding.
[The finite release plan](docs/development-roadmap.md) records those gates.

## Choose the workflow

| Workflow | Inputs | Result | Important boundary |
| --- | --- | --- | --- |
| Web research | Goal, columns/schema, explicit seeds or configured search | Accepted records, citations, snapshots, events and optional proof | Model suggestions require deterministic grounding and semantic review |
| Dataset preparation | Granted local files or declared HTTP GET sources | Typed or projected records and replayable source assets | Deterministic adapters make no model, search or browser calls |
| Large local preparation | CSV, TSV, JSONL, text or arbitrary asset bytes | Counts, paged records, checkpoints and streaming bundles | Separate ledger; no model research, large HTTP streaming or out-of-core sorting |

Arbitrary files can be captured and indexed with their hash. Capture does not mean
that an image, video, archive or scientific format has been understood. The
[capability registry](docs/formats.md) distinguishes exact parsing from capture-only
support. Time-series ordering and diagnostics require an explicit task policy.

## Install from this repository

Use Python 3.11–3.14 and Poetry. A C++ compiler is **not** required for normal use.
No public package availability is assumed by these instructions.

```bash
poetry install
poetry run verboisy --help
```

For web research, configure your provider privately in `.env`, then provision
Chromium with `poetry run verboisy setup`. Local dataset preparation does not start
a browser. Linux browser system libraries may require system provisioning; see
[installation and validation](docs/validation.md).

## Research a declared question

```bash
poetry run verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

Automatic discovery needs a configured search provider. Explicit browser seeds can
be declared in a task instead. Missing facts may remain `null`; unsupported facts
are rejected. Search snippets are discovery material, not final record evidence.
Use explicit JSON Schema and identity fields when inferred columns are insufficient.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

The ordinary `run`/`arun` API materializes accepted rows. It is not the gigabyte
streaming API. [CLI contracts](docs/cli.md) cover seeds, identity, grouping,
ordering, SmartID, proof and multiple exports.

## Prepare local or internal data

Grant the source directory explicitly; model credentials grant no filesystem access.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

CSV, JSON, JSONL, TSV, text, DOCX and XLSX have bounded deterministic adapters.
Declared HTTP GET sources use URL policy, bounded downloads, DNS pinning and
origin-scoped secret headers. OAuth, database drivers and service-specific API
pagination are separate connector requirements, not implicit HTTP capabilities.
See [source ingestion](docs/ingestion.md) and [file contracts](docs/formats.md).

## Prepare large local files

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

The separate streaming ledger retains immutable source chunks, bounded row batches
and transactionally committed progress. `stream-status` exposes job IDs; `stream
--resume JOB_ID` continues the saved contract. Python consumers page through
`StreamLedger` rather than receiving every row in one list.

| Recorded Linux/Python 3.12 workload | Measurement |
| --- | --- |
| Distinct JSONL rows | 1,000,000 |
| Source bytes | 1,105,888,890 |
| Peak process RSS | 89.15 MiB |
| Preparation and export | 130.81 seconds; 7,644.72 rows/second |
| Recovery and verification | Original source deleted; all exported rows, evidence and checksums verified |

This is one measured workload, not a guarantee for every machine, schema or format.
The [streaming contract](docs/streaming.md) documents resource ceilings, disk use,
portable bundle version and exclusions. Its raw report is retained under `evals/results`.

## Decisions, ranges and display choices

Verboisy can pause before export with a grounded alternative: a different search
scope, changed types, added columns or removed columns. Inspect its exact saved
contract with `verboisy changes --run-id RUN_ID`.

- `verboisy run --resume RUN_ID` continues the current requirements and declines the offer.
- `verboisy run --okresume RUN_ID` accepts the exact offered changes.

Observed intervals remain intervals. A lower bound does not become an exact number
or an invented maximum. Numeric min/max columns are a separate requested schema.
Defaults are kilograms, metres and day/month/year; explicit lb/ft/iso/mdy/source
preferences change presentation while preserving original evidence.

Explicit time-series tasks order actual instants within declared series and report
duplicates, invalid timestamps and declared-cadence gaps. Ambiguous daylight-saving
clock readings are not guessed. Diagnostics do not interpolate observations or
certify endpoint coverage. [Research semantics](docs/research-semantics.md) explains
these contracts and the scope of null-column notices.

## Inspect and recover

```bash
poetry run verboisy status --run-id RUN_ID
poetry run verboisy model-config
poetry run verboisy run --resume RUN_ID
```

Requests are budgeted and journaled; resume does not reset expenditure. Models
cannot accept their own proposed records. Compatible provider prefixes, custom
endpoints and local execution use explicit profiles; an arbitrary API is not
certified merely because a routing library can address it.
[Provider contracts](docs/providers.md) explain compatibility and role configuration.

Portable exports retain source assets or snapshots, evidence, relevant events and
output lineage. Grouped rows identify contributors; display transformations retain
raw values. Checksums establish integrity relative to the manifest, not factual
truth or independent authenticity. Inspect [proof and provenance](docs/proof.md).

## Engineering and release status

```bash
make validate
make repo-check
```

Validation covers lint, formatting, types, offline coverage, required browser
integration, dependency audit, strict documentation and package builds. Optional
C++ matchers retain Python references, native tests and measured build provenance;
see [native execution](docs/native.md). Platform, package and live acceptance must
be verified for the release commit, not inferred from an earlier run.

[Architecture](ARCHITECTURE.md) explains ownership, ledgers and trust boundaries.
[Maintainer workflow](.github/CONTRIBUTING.md), [security reporting](.github/SECURITY.md),
[release checklist](docs/release-checklist.md) and [commit policy](docs/commit-policy.md)
record operational expectations. External code contributions are not currently
accepted; authorized issue reports and product feedback remain welcome.

## Licensing and commercial readiness

The repository currently contains the BSD-2-Clause licence in [LICENSE](LICENSE).
Copyright notices and private development do not replace those terms. The intended
public distribution/commercial terms require review before publication; this batch
does not enact a new licence or register a trademark. Publication and funding are
separate from product qualification. See [distribution readiness](docs/distribution.md).

No exhaustive web coverage, perfect factual accuracy, access-control bypass or
universal file/provider compatibility is promised. Release readiness is determined
by recorded acceptance results and the seven gates, not repository size or language
percentages.
