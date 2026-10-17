<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Applied workflows

| Example | Purpose | Execution |
| --- | --- | --- |
| [Research catalogue](research_catalog/README.md) | Multi-source, multi-page facility records with compound identity and evidence | Real browser/model research against selected permitted sources; explicit `--live` |
| [Observation pipeline](streaming_observations/README.md) | Million-row and multi-gigabyte local preparation, checkpoints, resume and paging | Deterministic streaming; generated inputs explicitly marked synthetic |

Both examples use the public interfaces. They expose actual statuses and preserve
partial outcomes rather than replacing failure with a prepared result. Generated
inputs, ledgers, exports and recordings belong outside the tracked source tree.
Software execution requires the applicable [license](../LICENSE).


## Completion and prerequisites

Catalogue preview validates `/organization` and `/facility_name`; live research
requires browser/provider access and explicit budgets. The deterministic streaming
example prints its saved job ID and exits 2 on invocation pause. Resume that job after
source deletion, then verify completed status, every row, evidence sidecars and hashes.
Synthetic preparation is not evidence of successful live catalogue research.

## Local CLI quickstart

After activating the installed environment, run `python examples/local_quickstart.py`
from the repository root. It verifies two synthetic records and writes its isolated
outputs to `example-runs/`. It needs no model key or browser.
