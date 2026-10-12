<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="logo.png" alt="Verboisy" width="220" /></p>
<h1 align="center">Verboisy</h1>
<p align="center"><strong>From a research question to a dataset you can inspect.</strong></p>
<p align="center">Evidence-backed research · Structured extraction · Local data preparation · Portable provenance</p>
<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml/badge.svg" alt="Continuous integration" /></a>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB" alt="Python 3.11–3.14" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Source%20inspection%20only-7057ff" alt="Source inspection license" /></a>
</p>
<p align="center"><a href="#what-verboisy-does">Overview</a> · <a href="#getting-started">Getting started</a> · <a href="#documentation">Documentation</a> · <a href="#licensing-demos-and-commercial-enquiries">Demos & licensing</a></p>

<p align="center">
  <a href=".github/readme/README.it.md">Italiano</a> ·
  <a href=".github/readme/README.de.md">Deutsch</a> ·
  <a href=".github/readme/README.fr.md">Français</a> ·
  <a href=".github/readme/README.es.md">Español</a> ·
  <a href=".github/readme/README.ja.md">日本語</a> ·
  <a href=".github/readme/README.ko.md">한국어</a> ·
  <a href=".github/readme/README.zh-CN.md">简体中文</a>
</p>

## What Verboisy does

Verboisy is a research and data extraction engine for people who need structured
information and a way to inspect where it came from. Define a question, a schema
and permitted sources. Verboisy acquires observations, checks proposed records,
retains evidence and produces datasets with traceable output transformations.

The same project also prepares existing local and declared HTTP datasets through
deterministic adapters. A separate streaming workflow handles large local inputs
without returning every row in one in-memory list. The CLI and Python API support
repeatable workflows, saved state and explicit recovery.

**Source-visible, commercially licensed.** Reading the source is permitted under
[LICENSE](LICENSE). Running, testing, modifying or deploying Verboisy requires a
separate written license. The examples below describe authorized use. For a demo,
evaluation or enterprise license, contact [Emanuele Torrisi](mailto:emanueletorrisi98@gmail.com).

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

See [file capabilities](docs/formats.md) for precise contracts. Binary capture is
not OCR, image understanding or universal document extraction. Service-specific
connectors, OAuth flows and API pagination require explicit integrations.

## Workflows in practice

- [Multi-source research catalogue](examples/research_catalog/README.md): define
  permitted sources, a compound identity and a target of 100 grounded facility records.
- [Large local observation pipeline](examples/streaming_observations/README.md):
  generate multi-gigabyte synthetic input, pause and resume preparation, then page
  through committed records without loading the dataset into memory.

These are executable workflows, not prerecorded results. Research uses the selected
model and actual sources; the scale example labels its generated data as synthetic.
See [evaluation](docs/evaluation.md) for the meaning of workload measurements.

## Getting started

### Requirements

- Python **3.11–3.14** and Poetry; Linux, macOS and Windows are covered by CI.
- A written evaluation or usage license for execution.
- For model-based research, an approved provider profile and its credentials.
- For browser acquisition, Chromium and the required system libraries.
- For local ingestion, an explicit source-directory grant and sufficient disk space.

Normal installation requires **no C++ compiler**. Optional native components have
Python reference paths and separate build instructions. Deterministic local data
preparation does not require a model key or a browser.

From an authorized checkout:

```bash
poetry install
poetry run verboisy --help
```

Keep provider credentials in your private environment or `.env`; start from
[.env.example](.env.example). Do not commit populated secrets. Provision Chromium
when using web research:

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

Shell examples use POSIX syntax; on Windows, configure environment variables using
the equivalent shell syntax or your private `.env`.

The configuration inspector reports settings and credential presence without
printing key values. Review [provider configuration](docs/providers.md) and
[installation checks](docs/validation.md) before connecting a provider.

### Research a question

```bash
poetry run verboisy run \
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
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

The directory and schema file must exist. Model credentials do not grant filesystem
access. Declared HTTP sources use bounded downloads, redirect policy, DNS-pinned
transport and origin-scoped credentials. A local source workflow can remain local;
choosing a remote model separately determines what observation content is sent
outside the machine. Review [ingestion](docs/ingestion.md) and [enterprise deployment](docs/commercial.md).

### Prepare large local inputs

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

The streaming ledger retains source chunks and transactionally committed progress.
`stream-status` lists jobs; `stream --resume JOB_ID` continues a saved job. Python
consumers page through `StreamLedger` instead of loading all rows at once.

A recorded Linux/Python 3.12 workload prepared and exported **1,000,000 JSONL rows**
from **1,105,888,890 input bytes**, with **89.15 MiB peak process RSS** and **130.81 s**
elapsed time. Recovery after deletion of the original source and export integrity
were verified. These measurements describe one workload, not a universal speed or
memory guarantee. See [streaming](docs/streaming.md) and [benchmarks](docs/benchmarks.md).

## Review, resume and inspect

Verboisy may offer a grounded alternative when requirements conflict with the
observed data: different types, added or removed columns, or another search scope.
Inspect the exact proposal before deciding:

```bash
poetry run verboisy changes --run-id RUN_ID
poetry run verboisy status --run-id RUN_ID
poetry run verboisy run --resume RUN_ID
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
source authenticity. See [proof and provenance](docs/proof.md).

## Architecture and engineering

Python owns orchestration, contracts, adapters, ledgers and the CLI. Optional C++17
components accelerate specific evidence-matching work while preserving Python
reference semantics. SQLite provides durable research and streaming state.

The test suite covers request boundaries, grounding, replay, malformed inputs,
interruption, output lineage and browser integration. CI checks supported Python
and operating-system combinations; full statement and branch coverage is required.
Model compatibility and real-task quality depend on the selected profile and sources
and require their own evaluation.

[Architecture](ARCHITECTURE.md) explains component ownership, data flow and trust
boundaries. [Validation](docs/validation.md) describes reproducible engineering checks.

## Documentation

| Start here | Technical references |
| --- | --- |
| [CLI reference](docs/cli.md) · [Python API](docs/api.md) | [Contracts](docs/contracts.md) · [Identity and SmartID](docs/smartid.md) |
| [Source ingestion](docs/ingestion.md) · [File capabilities](docs/formats.md) | [Projection and source evidence](docs/proof.md) · [Search and recovery](docs/search-and-recovery.md) |
| [Presentation](docs/presentation.md) · [Research semantics](docs/research-semantics.md) | [Providers](docs/providers.md) · [Large local datasets](docs/streaming.md) |
| [Security policy](.github/SECURITY.md) · [Reporting and collaboration](.github/CONTRIBUTING.md) | [Release notes](CHANGELOG.md) · [Version evolution](docs/development-roadmap.md) |
| [Licensing](docs/licensing.md) · [Commercial enquiries](docs/commercial.md) | [Copyright and third-party notices](COPYRIGHT.md) |

## Licensing, demos and commercial enquiries

Verboisy is proprietary software with source inspection permissions, **not an
open-source project**. Execution, testing, modification, integration, deployment
and redistribution require separate written permission. [LICENSE](LICENSE) is the
authoritative English text; translations of this README do not alter its terms.
Third-party components retain their respective licenses.

Contact **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** for:

- A guided demo or an evaluation tailored to your data workflow.
- Internal-use, enterprise, integration or other commercial licensing.
- Investment, partnerships or business discussions.
- Potential paid engineering collaboration under an agreed contract.

Describe the workflow, source types, expected volume and deployment environment.
Do not send confidential datasets or credentials in an initial enquiry. Pricing,
support, delivery dates and usage rights are agreed individually.

## Commercial solutions and product direction

Verboisy welcomes independent professionals, researchers, startups, agencies and
enterprise teams. Commercial discussions can start with a single workflow:
a guided evaluation, usage licensing, integration work or deployment planning.

The paid product direction includes managed research, scheduled workflows, team
workspaces, internal-source connectors, private deployments, high-volume workload
management, integration interfaces, quality tooling and support agreements.
Availability, delivery and service commitments are confirmed in each proposal.
See [commercial solutions](docs/commercial.md) for the scope and enquiry process.

The public repository is intended to receive maintained, documented updates as
Verboisy develops. Commercial extensions and managed-service infrastructure may
be distributed separately. Source visibility and product updates do not change
the permissions set out in [LICENSE](LICENSE).

## Feedback and collaboration

Verboisy is created and maintained by **Emanuele Torrisi**, currently the project's
sole developer. Bug reports and feature requests are welcome through
[GitHub Issues](https://github.com/EmanueleTorrisi/verboisy/issues). Report security
issues privately using the [security policy](.github/SECURITY.md).

Unsolicited code contributions are not currently accepted. Future paid collaboration
may be arranged where it fits the product roadmap; discuss scope, compensation and
intellectual-property terms before beginning work. See [participation guidelines](.github/CONTRIBUTING.md).

Subsequent versions are recorded in the [changelog](CHANGELOG.md). The
[version roadmap](docs/development-roadmap.md) documents the progression from 0.1.0
to the current architecture. Source permissions, independent review and measured
task outcomes define the scope of a research result.
