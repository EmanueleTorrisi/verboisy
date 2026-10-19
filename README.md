<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="https://raw.githubusercontent.com/EmanueleTorrisi/verboisy/main/logo.png" alt="Verboisy" width="220" /></p>
<h1 align="center">Verboisy</h1>
<p align="center"><strong>From a research question to a dataset you can inspect.</strong></p>
<p align="center">Evidence-backed research · Structured extraction · Local data preparation · Portable provenance</p>
<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml/badge.svg" alt="Continuous integration" /></a>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB" alt="Python 3.11–3.14" />
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Source%20inspection%20only-7057ff" alt="Source inspection license" /></a>
</p>
<p align="center"><a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md#what-verboisy-does">Overview</a> · <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md#see-the-cli-in-use">Demo</a> · <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md#getting-started">Getting started</a> · <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md#documentation">Documentation</a> · <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md#licensing-demos-and-commercial-enquiries">Demos & licensing</a></p>

<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.it.md">Italiano</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.de.md">Deutsch</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.fr.md">Français</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.es.md">Español</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ja.md">日本語</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ko.md">한국어</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.zh-CN.md">简体中文</a>
</p>

> **Release status:** Version `1.0.0` is ready for production use within the documented workflows, supported environments and tested limits. The [release matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) records the supporting engineering checks, real-task evaluation, independent beta and release-owner approvals.

## What Verboisy does

Verboisy is a research and data extraction engine for people who need structured
information and a way to inspect where it came from. Define a question, a schema
and permitted sources. Verboisy acquires observations, checks proposed records,
retains evidence and produces datasets with traceable output transformations.

Verboisy also prepares existing local and declared HTTP datasets through
deterministic adapters. A separate streaming workflow handles large local inputs
without returning every row in one in-memory list. The CLI and Python API support
repeatable workflows, saved state and explicit recovery.

**Source-visible, commercially licensed.** Reading the source is permitted under
[LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE). Running, testing, modifying or deploying Verboisy requires a
separate written license. The examples below describe authorized use. For a demo,
evaluation or enterprise license, contact [Emanuele Torrisi](mailto:emanueletorrisi98@gmail.com).

## See the CLI in use

[Watch the terminal recording](https://asciinema.org/a/kao32h7xRRkFwtkc).

Follow `verboisy run` from a goal and schema to exported data. The NASA example
uses a saved capture to demonstrate deterministic dataset preparation.

The terminal preview shows up to five rows and five columns. Long headings and
values end with `...`; preview clipping does not change the exported data.

## Why this approach matters

A JSON response or a scraped table does not explain whether a fact was observed,
whether two measurements are comparable, or how a displayed value was derived.
Verboisy makes those questions part of the data workflow:

- **Evidence before acceptance.** Model-generated candidates need observed source
  bindings and deterministic verification; semantic review is a separate boundary.
- **A data contract you control.** JSON Schema, identity rules, source scope and
  comparability requirements define acceptable output.
- **Recoverable work.** Persistent frontiers, immutable source captures, request
  journals and checkpoints preserve progress and expenditure across resume.
- **Explainable transformations.** Unit conversion, display choices, projections
  and grouped results retain links to their raw evidence and contributors.
- **Explicit decisions.** Proposed changes pause work for review instead of silently
  substituting a different question or schema.

This is useful for analyst research, reference-data collection, data preparation,
internal information workflows and reproducible investigations. Scientific and
regulated uses still require independent review of sources, sampling and conclusions.
Verboisy's long-term ambition is to become a trusted standard for evidence-backed
data extraction; that is a product direction, not a claim of market leadership.

### Use AI where interpretation adds value

Verboisy combines deterministic code with semantic AI. Parsing structured files,
validating schemas, matching observed evidence and exporting data run in code;
models support planning and interpretation where the workflow calls for them.
Deterministic steps consume no model tokens, avoiding the inference charges that
would arise from sending those same operations to a paid LLM. Local dataset
preparation can run entirely without a model provider.

This design reduces unnecessary model use and makes spending easier to inspect.
End-to-end savings depend on the task, model, retries and review effort. A fair
comparison measures the same sources, output requirements and quality threshold,
including failed work. Evidence checks reduce unsupported output; semantic
correctness remains subject to source quality and review.

## Choose your workflow

| Workflow | Typical input | Output | Execution |
| --- | --- | --- | --- |
| Web research | A question, columns or schema, permitted sites | Structured records, evidence and saved research state | Browser and configured model; optional search discovery |
| Dataset preparation | Granted local files or declared HTTP GET sources | Validated/projected records and retained source assets | Deterministic parsing without model, search or browser calls |
| Large local preparation | CSV, TSV, JSONL, text or asset bytes | Paged records, counts, durable checkpoints and streaming bundles | Separate disk-backed ledger and bounded buffers |

| Input capability | Supported interpretation |
| --- | --- |
| CSV / TSV | Exact text fields, explicit headers and row-width checks |
| JSON / JSONL | Typed object records with strict decoding |
| Text | Text records with source locations |
| DOCX / XLSX | Bounded, documented Office adapters; no macro or formula execution |
| Other files, including images or video | Immutable byte capture, hashes and reference records; no automatic content interpretation |
| Time-series observations | Explicit series/timestamp policies, ordering and gap/duplicate diagnostics |

See [file capabilities](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md) for precise contracts. Binary capture is
not OCR, image understanding or universal document extraction. Service-specific
connectors, OAuth flows and API pagination require explicit integrations.

## Workflows in practice

- [Multi-source research catalogue](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md): define
  permitted sources, a compound identity and a target of 100 grounded facility records.
- [Large local observation pipeline](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md):
  generate multi-gigabyte synthetic input, pause and resume preparation, then page
  through committed records without loading the dataset into memory.

These are executable workflows, not prerecorded results. Research uses the selected
model and actual sources; the scale example labels its generated data as synthetic.
See [evaluation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/evaluation.md) for the meaning of workload measurements.

## Getting started

### Requirements

- Python **3.11–3.14**. Use the operating-system and interpreter profiles recorded in the release matrix.
- A written evaluation or usage license for execution.
- For model-based research, an approved provider profile and its credentials.
- For browser acquisition, Chromium and the required system libraries.
- For local ingestion, an explicit source-directory grant and sufficient disk space.

Normal installation requires **no C++ compiler**. Optional native components have
Python reference paths and separate build instructions. Deterministic local data
preparation does not require a model key or a browser.

From an authorized source checkout, install the CLI in an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

Then use **`verboisy run`** directly. Poetry is a development tool, not a prefix
required by the installed command. For a command available outside this checkout,
use `pipx install .` after installing pipx. Once an authorized public release is
published, the equivalent is `pipx install verboisy`. Publication is not assumed.
See [installation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) for pipx, wheels, Python imports and Windows.

Try the actual local CLI without model keys or a browser:

```bash
python examples/local_quickstart.py
```

This example verifies two **synthetic** records and saves the data and evidence in
`example-runs/`. It demonstrates deterministic ingestion, not real-world research quality.

Keep provider credentials in your private environment or `.env`; start from
[.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example). Do not commit populated secrets. Provision Chromium
when using web research:

```bash
verboisy setup
verboisy model-config
```

Shell examples use POSIX syntax; on Windows, configure environment variables using
the equivalent shell syntax or your private `.env`.

The configuration inspector reports settings and credential presence without
printing key values. Review [provider configuration](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md) and
[installation checks](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md) before connecting a provider.

### Research a question

```bash
verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

Automatic discovery needs a configured search provider; explicit seeds can instead
be declared in a task. Use JSON Schema when types, required fields and validation
rules need precise control. Missing facts may remain `null`; unsupported values are
rejected. Accepted results do not imply exhaustive coverage of the web.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

Async applications use `arun`. The ordinary research API materializes accepted
rows; use the streaming API for large local inputs.

### Prepare local or internal data

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
verboisy run \
  --goal "Prepare the local observations using the supplied schema and preserve source values" \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --mass-unit source --length-unit source --date-format source \
  --export observations.json
```

The directory and schema file must exist. Model credentials do not grant filesystem
access. Declared HTTP sources use bounded downloads, redirect policy, DNS-pinned
transport and origin-scoped credentials. A local source workflow can remain local;
choosing a remote model separately determines what observation content is sent
outside the machine. Review [ingestion](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) and [enterprise deployment](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md).

### Prepare large local inputs

```bash
verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

The streaming ledger retains source chunks and transactionally committed progress.
`stream-status` lists jobs; `stream --resume JOB_ID` continues a saved job. Python
consumers page through `StreamLedger` instead of loading all rows at once.

A historical, source-specific Linux/Python 3.12 workload prepared and exported **1,000,000 JSONL rows**
from **1,105,888,890 input bytes**, with **89.15 MiB peak process RSS** and **130.81 s**
elapsed time. Recovery after deletion of the original source and export integrity
were verified. These measurements describe one workload, not a universal speed or
memory guarantee. See [streaming](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md) and [benchmarks](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md).

## Review, resume and inspect

Verboisy may offer a grounded alternative when requirements conflict with the
observed data: different types, added or removed columns, or another search scope.
Inspect the exact proposal before deciding:

```bash
verboisy changes --run-id RUN_ID
verboisy status --run-id RUN_ID
verboisy run --resume RUN_ID
```

`--resume` keeps the current requirements and declines the offer. `--okresume`
accepts the exact saved proposal. Resume retains consumed budgets; it does not
reset expenditure or silently authorize additional sources.

Ranges stay ranges. A lower bound does not become an exact weight or an invented
maximum. Numeric minima and maxima require an appropriate schema. Presentation
defaults are kilograms, metres and day/month/year, with explicit alternatives;
original values remain in the evidence. Time-series diagnostics do not fill missing
observations or resolve ambiguous local times by guessing.

Portable exports include evidence, relevant events, output lineage and retained
source material where applicable. Grouped rows identify their contributing records.
Checksums establish byte consistency with the manifest, not independent truth or
source authenticity. See [proof and provenance](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md).

## Architecture and engineering

Python owns orchestration, contracts, adapters, ledgers and the CLI. Optional C++17
components accelerate specific evidence-matching work while preserving Python
reference semantics. SQLite provides durable research and streaming state.

The test suite covers request boundaries, grounding, replay, malformed inputs,
interruption, output lineage and browser integration. CI checks supported Python
and operating-system combinations; full statement and branch coverage is required.
Model compatibility and real-task quality depend on the selected profile and sources
and require their own evaluation.

[Architecture](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) explains component ownership, data flow and trust
boundaries. [Validation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md) describes reproducible engineering checks.

## Documentation

| Start here | Technical references |
| --- | --- |
| [CLI reference](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [Python API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) | [Contracts](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [Identity and SmartID](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) |
| [Source ingestion](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [File capabilities](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md) | [Projection and source evidence](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md) · [Search and recovery](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/search-and-recovery.md) |
| [Presentation](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [Research semantics](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) | [Providers](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md) · [Large local datasets](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md) |
| [Security policy](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md) · [Reporting and collaboration](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md) | [Release notes](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md) · [Version evolution](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md) |
| [Licensing](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md) · [Commercial enquiries](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md) | [Copyright and third-party notices](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md) |

## Licensing, demos and commercial enquiries

Verboisy is proprietary software with source inspection permissions, **not an
open-source project**. Execution, testing, modification, integration, deployment
and redistribution require separate written permission. [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE) is the
authoritative English text; translations of this README do not alter its terms.
Third-party components retain their respective licenses.

Contact **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** for:

- A guided demo or an evaluation tailored to your data workflow.
- Internal-use, enterprise, integration or other commercial licensing.
- Product partnerships and business discussions.
- Potential paid engineering collaboration under an agreed contract.

Describe the workflow, source types, expected volume and deployment environment.
Do not send confidential datasets or credentials in an initial enquiry. Pricing,
support, delivery dates and usage rights are agreed individually.

## Why choose a commercial agreement?

This repository contains **Verboisy’s public source-inspection edition**. Commercial
customers receive a **separately maintained edition with additional capabilities**
that are not distributed in this repository.

The [commercial comparison](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md) describes edition scope, deployment options and services.
Commercial release notes and the signed agreement identify the additional features
delivered to the customer. The public repository
will continue to receive updates.

Delivered features, usage rights, support, update entitlement, fees and delivery
dates are specified in the signed agreement.

| Your goal | What to agree commercially |
| --- | --- |
| Use Verboisy in daily work | Written execution and internal-use rights for the agreed users and environment |
| Integrate research into your product | Modification, integration and deployment rights appropriate to that product |
| Reduce setup and evaluation work | Scoped onboarding, schema design and a representative acceptance exercise |
| Fit private infrastructure | Deployment assessment and integration work for approved sources and networks |
| Plan maintenance and assistance | Explicit update entitlement, support scope and response commitments |
| Deliver work to clients | Agreed service, redistribution or embedding rights where needed |

Choose the edition and service scope against your actual workflow: required
capabilities, deployment constraints, acceptance criteria and ongoing maintenance.
The commercial agreement makes those deliverables and responsibilities explicit.

[Discuss your workflow](mailto:emanueletorrisi98@gmail.com) ·
[Commercial scope](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md) · [Distribution options](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/distribution.md)

## Feedback and collaboration

Verboisy is created and maintained by **Emanuele Torrisi**, currently the project's
sole developer. Bug reports and feature requests are welcome through
[GitHub Issues](https://github.com/EmanueleTorrisi/verboisy/issues). Report security
issues privately using the [security policy](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md).

Unsolicited code contributions are not currently accepted. Future paid collaboration
may be arranged where it fits the product roadmap; discuss scope, compensation and
intellectual-property terms before beginning work. See [participation guidelines](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md).

Subsequent versions are recorded in the [changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md). The
[version roadmap](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md) documents the progression from 0.1.0
to the current architecture. Source permissions, independent review and measured
task outcomes define the scope of a research result.


## Data and qualification boundaries

Ordinary output reserves top-level `id` for generated row metadata. Rename source IDs
explicitly to `source_id` with a [projection](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md#explicit-projection-engine);
nested IDs and streaming source IDs remain supported. Optional fields remain absent
when unobserved; an explicit nullable null remains present.

Streaming validates individual rows. Array-root item counts, uniqueness, contains,
combinators and conditionals are rejected, rather than silently ignored. Preparation
exits 0 when completed, 2 when paused, 1 when failed and 130 when interrupted;
read-only inspection can succeed for an incomplete job.

Production qualification is tied to the released source, approved workflows and
recorded environments. Historical scale measurements retain their original source
and host context. Current engineering results, acceptance evidence and release
approvals are recorded in
[release matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) and [release guide](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md).
