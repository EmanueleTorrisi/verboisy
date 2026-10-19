<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Applied workflows

Verboisy provides separate interfaces for research and large local data preparation.
The examples below use those actual interfaces and expose source scope, resource
ceilings, status and recovery rather than providing prerecorded output.

## Multi-source research catalogue

The [research catalogue](https://github.com/EmanueleTorrisi/verboisy/tree/main/examples/research_catalog)
collects scientific facilities from selected institutional directories. A seven-field
schema distinguishes organization, facility, category, country, city, homepage and
published services. A compound identity and a 100-record target make the task explicit.

The script previews its contract without making requests. `--live` starts actual
model/browser research under host, page and request ceilings. It exports accepted
JSON/CSV records with evidence and reports partial or failed outcomes accurately.
Sources are selected by the caller; no fictitious URLs are advertised as acquired data.

## Large local observation pipeline

The [observation pipeline](https://github.com/EmanueleTorrisi/verboisy/tree/main/examples/streaming_observations)
generates distinct synthetic observations, including timestamps and explicit units.
The generator can write multi-gigabyte input with bounded memory and reports its actual
byte count and SHA-256. The processing script pauses at a row budget, resumes from
captured bytes, exports evidence-bearing JSONL and reads a bounded sample with paging.

Generation is a workload, not internet research. Recorded [scale measurements](streaming.md)
identify their implementation and environment. Gigabyte input files are generated
locally rather than stored in the repository.

## Demonstrations

[Watch the Verboisy CLI recording](https://asciinema.org/a/kao32h7xRRkFwtkc) to see the command-line workflow.
The NASA example prepares a saved capture through the local dataset path. It
demonstrates schema-driven preparation and export; live web acquisition and model
interpretation are separate workflows.

The ordinary result preview displays up to five rows and five columns, with `...`
for clipped text. Exported data retains the full result. See the [CLI reference](cli.md)
for schema syntax and output options.

A product demonstration can show the same workflows with actual execution and output.
For a guided session using your sources and schema, contact
[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com).

A research demonstration should identify the selected sources, version, model profile,
schema, target, status and reviewed evidence. A scale demonstration should identify
synthetic input, byte/row counts, limits, elapsed time and memory separately. Time-lapse
or edited pauses should be labelled so they do not imply a shorter runtime.


## Executable contracts

The catalogue declares compound pointers `/organization` and `/facility_name`; preview
validates that research contract without paid work. Live execution requires permitted
sources, browser infrastructure and configured provider budget.

Project ordinary source IDs to `source_id`, preserving generated public IDs. Optional
unobserved fields stay absent. SmartID reads manifest-declared modes and verifies the
reference hash; plain CSV remains text. The local streaming example pauses with exit 2
and resumes by its printed job ID after deletion of the original captured source.
See [catalogue](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) and
[streaming observations](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md).

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
