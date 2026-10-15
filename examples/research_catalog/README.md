<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Multi-source research catalogue

Build a structured catalogue of scientific facilities from selected institution,
laboratory or infrastructure directories. The schema records the owning organization,
facility name, published category, country, city, website and services. Compound
identity distinguishes facilities with the same name at different organizations.

The task targets 100 accepted records across multiple source pages. The target is a
completion requirement, not a promise that every selected source contains enough
supported records. Unsupported fields remain null; scope and source bindings still
apply to each observation. The ordinary research API materializes accepted rows.

## Select sources and inspect the contract

The supplied source manifest contains actual Department of Energy and Brookhaven
research-facility directories, selected on 11 October 2026. These are source entry
points, not saved extraction results. Review access permissions and current scope
before execution; source availability and content can change.

```bash
poetry run python examples/research_catalog/research.py --target 100 --max-pages 200
```

Repeat `--seed` to replace the supplied selection with permitted URLs:

```bash
poetry run python examples/research_catalog/research.py \
  --seed 'https://www.energy.gov/science/office-science-user-facilities' \
  --seed 'https://www.bnl.gov/science/facilities.php' \
  --target 100 --max-pages 200
```

Without `--live`, the script only validates and prints the task. It does not start
a browser, model call or search provider. Additional linked hosts require an explicit
`--allow-host`; do not broaden permissions merely to make a run complete.

## Execute research

Configure a compatible model and provision Chromium as described in the main
[README](../../README.md). Execution requires the applicable license and can incur
provider charges. The example disables search discovery and uses a 300,000-unit
model request ceiling unless explicitly overridden; units are not billed tokens.

```bash
poetry run python examples/research_catalog/research.py \
  --seed 'https://www.energy.gov/science/office-science-user-facilities' \
  --seed 'https://www.bnl.gov/science/facilities.php' \
  --target 100 --max-pages 200 --steps 12 \
  --output example-runs/research-catalog --live
```

Each invocation visits a bounded number of pages. JSON/CSV, evidence, events,
manifest and proof files retain the accepted observations and their lineage. A
paused or exhausted run may contain useful partial output but is not presented as
completed research. The script prints its run ID, ledger path and stop reason.

## Resume and review

Set `SQLITE_DB_PATH` to the printed ledger path, then inspect the actual run ID:

```bash
poetry run verboisy status --database example-runs/research-catalog/research.db --run-id RUN_ID
poetry run verboisy changes --database example-runs/research-catalog/research.db --run-id RUN_ID
```

Resume uses the configured `SQLITE_DB_PATH`:

```bash
SQLITE_DB_PATH=example-runs/research-catalog/research.db \
  poetry run verboisy run --resume RUN_ID
```

`--resume` retains requirements and declines an offered change; `--okresume` accepts
the saved proposal. Budgets and source scope persist. Review the evidence and selected
sources before making completeness claims or using records in downstream analysis.

For a real product recording, use the selected sources and the actual resulting rows;
do not replace a failed run with the synthetic browser regression fixture.


## Compound identity and evidence

The executable compound identity is `/organization` plus `/facility_name`. Preview
validates declared scalar pointers before creating a directory or run. Synthetic
verifier regressions establish pointer lookup, not real facility research success.
Live use needs authorized sources, browser infrastructure, provider credentials and
bounded request/page budgets; captures and manifests disclose their evidence limits.
