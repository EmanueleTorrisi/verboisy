<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Release qualification

Verboisy 2.0.0 covers production use for local dataset preparation and extraction from
declared public sources. The [changelog](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md#200) records feature and compatibility changes.
Release records link engineering, workflow and distribution evidence to the exact
source revision and package artifacts. The [release matrix](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json) defines
the review criteria and records the approvals for publication.

## Three files, three responsibilities

| File | Responsibility | Update when |
| --- | --- | --- |
| README and all seven translations | Product, installation, limits and commercial scope | User-facing claims change |
| `docs/evaluation.md` | Methods, measurements and campaign design | Evaluation design changes |
| `evals/release-matrix.json` | Tasks, targets and seven release reviews | Plans are approved or evidence is reviewed |

Reports under `evals/results/` retain the source revision, execution environment and
workload for each result.

## Execute engineering checks

From the repository root after [bootstrap](installation.md):

```bash
source .venv/bin/activate
python scripts/verify_release.py --native --audit --package
python scripts/release_matrix.py status
```

Checks cover the lock, repository contracts, lint, formatting, types, offline tests
at **100% statement and branch coverage**, the real local CLI, strict docs, native
builds/tests, dependency auditing, wheel/sdist contracts, rebuilding from sdist,
fresh installation and strict Twine checks. Native checks require a C++ toolchain.
Missing tools and network failures are failures, never silently passing gates.

The verifier writes a timestamped JSON report and logs under `build/release-checks/`.
It never marks matrix gates complete. Logs may contain local paths or source data;
review them before sharing. Redacting evidence changes its hash and requires review.

For real Chromium checks after provisioning the browser and system libraries:

```bash
verboisy setup
VERBOISY_REQUIRE_BROWSER=1 python scripts/verify_release.py --native --browser --audit --package
```

CI has sandbox-disabled browser tests for a constrained runner and a separate Docker
sandbox smoke test. Intended production sandbox/egress behavior needs its own evidence.

## Release acceptance requirements

| Gate | Work required | Completion evidence |
| --- | --- | --- |
| 1 · Contract and design | Approve scope, sources, independent gold annotations, targets and aggregate EUR budget | Approved plan, permitted capture hashes and annotation records |
| 2 · Real acceptance | Review a three-task pilot, execute 69 runs, qualify advertised source/format/provider combinations | Raw successes, failures, outputs, evidence and measured quality |
| 3 · UX and economics | New-user CLI/API installation, real demo, actual billed cost and end-to-end latency | Session outcomes, demo, billing and timing records |
| 4 · Reliability | Engineering checks, supported-platform CI, real browser, Docker, security, current scale and claimed durability tests | Source-specific reports and infrastructure results |
| 5 · Editorial and legal | All languages, metadata, complete Git history for secrets, ownership, prior BSD grants and terms | Editorial review, investigated secret findings and qualified legal review |
| 6 · Independent beta | Authorized independent user performs representative work; blockers are fixed and retested | Beta report, issue resolutions and sign-off |
| 7 · Delivery | Rehearse the selected channel; approve claims, demo, support, rollback and private access policy | Exact artifact hashes, installation receipt and release-owner approval |

Detailed criteria are in the matrix. Local engineering cannot replace live task
evaluation, independent beta or legal review.

## Approve the paid campaign plan

```bash
python scripts/release_matrix.py configure-plan
git add -- evals/release-matrix.json
git commit -m "chore(release): approve evaluation budget and performance limits"
```

The command prompts for positive finite limits, total EUR budget and plan owner.
It requires `APPROVE PLAN` and makes no provider calls. Finalize sources, gold data
and scope before gate reviews; changes invalidate older source-bound reviews.
See [evaluation](evaluation.md) for the campaign protocol and reviewer responsibilities.

## Save actual evidence from the terminal

Store release evidence in `evals/results/`. Review records identify the reviewer, source
revision and digest, executed checks, findings, and artifact hashes.

```bash
cat > evals/results/editorial-review.md
```

Public review records can reference private evidence by checksum without exposing
confidential agreements or personal data.

Give every evidence file its own commit:

```bash
git add -- evals/results/editorial-review.md
git commit -m "docs(release): record editorial review evidence"
```

## Mark one gate complete

Run only when every criterion for the chosen gate is supported:

```bash
read -r -p "Gate number (1–7): " VERBOISY_GATE
read -r -p "Reviewer name: " VERBOISY_REVIEWER
read -r -p "Evidence path under evals/results/: " VERBOISY_EVIDENCE
python scripts/release_matrix.py review \
  --gate "$VERBOISY_GATE" --reviewer "$VERBOISY_REVIEWER" \
  --evidence "$VERBOISY_EVIDENCE"
git add -- evals/release-matrix.json
git commit -m "chore(release): record gate $VERBOISY_GATE evidence review"
```

`--evidence` accepts multiple paths. The script prompts for a finding per criterion
and an exact attestation. It records reviewer, date, revision, source digest and
evidence hashes. It cannot independently validate a reviewer's claims or legal opinion.

```bash
python scripts/release_matrix.py status
python scripts/release_matrix.py require-complete
```

The second command fails until all seven reviews match current source and evidence.
The source digest excludes review bookkeeping and reports. Changes to code,
dependencies, documentation, tests or the evaluation plan require renewed source-bound
reviews. The release owner records the delivery decision separately.

## Select the tested package

Use the passing report path printed by the verifier:

```bash
read -r -p "Passing engineering report path: " VERBOISY_REPORT
python scripts/package_release.py prepare --report "$VERBOISY_REPORT"
python scripts/package_release.py show
```

This selects the exact tested wheel and sdist without rebuilding different bytes.
Their hashes and source are checked again before use. Nothing is uploaded.
Continue with [public publication or private delivery](distribution.md).
