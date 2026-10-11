<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Production acceptance contract

Status: **proposed for maintainer review**. This document establishes measurable
release gates, not results already achieved. The target is general-purpose research
across domains, rather than a business-only product. The machine-readable case
inventory is `evals/release-matrix.json`.

## Supported product scope

The first supported release provides the CLI and Python API for a single local
user, public HTTP(S) research and declared CSV/JSON/JSONL ingestion. It accepts
user-owned schemas, source policies and stable identity fields; retains observed
evidence; and exports JSON/CSV with lineage, manifests and optional proof reports.

Coverage must span people, organisations, products, events, locations and numeric
or temporal measurements. This is a domain-agnostic product goal. It does not
promise universal success on every source or make unobserved facts observable.

The supported boundary is observed HTML, including browser-rendered content and
linked or explicitly configured pagination, within declared crawl and resource
limits. Login flows, paywalls, CAPTCHA bypass, PDF/image/OCR extraction, spreadsheets
other than supported CSV, arbitrary currencies/unit systems and automatic semantic
cross-page joins are not qualified by this release. New formats need their own
acceptance evidence before being advertised. Multilingual content and Unicode
preservation are tested; translated README availability alone does not establish
query-language accuracy.

Normal installation must work without a C++ compiler. Existing native matching
remains useful and optional, with reference-equivalence and supported-platform
validation required before native acceleration claims.

## Extended qualification requirements

The small held-out pilot establishes correctness; it does not certify the eventual
capacity or full product scope. Large research datasets, time series, binary asset
collections and enterprise sources are explicit requirements for further
qualification. They must remain visible in the release plan rather than being
inferred from a passing small-input test suite.

| Capability | Current implementation boundary | Evidence needed before qualification |
| --- | --- | --- |
| Large datasets | Downloads and parsing default to 16 MiB; rows are materialized in memory; requested record targets are capped at 100,000 | Streaming ingestion/export, bounded memory, millions of rows and gigabyte inputs, checkpoint recovery, disk limits and measured throughput/cost |
| Time series | Timestamped records can use ordinary schemas; JSON can retain nested structure | Timestamp/timezone preservation, explicit ordering and duplicate policy, missing observations, interval and reference-time semantics |
| Image and other binary collections | Declared dataset formats are CSV, JSON and JSONL; binary image acquisition is not a supported dataset workflow | Asset capture with hashes, format/size checks, rights metadata where available, portable reference manifests and resumable export; OCR/captioning require separate qualification |
| Local and enterprise sources | CLI and SQLite execute locally; production acquisition uses HTTP(S) sources | Explicit local/web/internal source selection, filesystem permissions, approved internal hosts, credentials isolation, connector tests and no-egress verification |

These requirements need representative end-to-end workloads and their own
resource profiles. Raising size limits alone does not establish safe scale. A
local source mode must not silently weaken public-web network protections, and
local storage must not be advertised as fully offline processing while model
requests can leave the machine. The source mode and model execution mode are
separate decisions.

Dataset creation can form the foundation of a broader dataset platform. Hosting,
discovery, sharing, collaboration and marketplace functions require separate
product scope; successful export alone does not qualify those capabilities.

## User-visible contract

1. A non-null accepted value must be supported by its observed entity evidence.
   Source support and publisher truth are distinct; the product must not conflate them.
2. Required unsupported values cause rejection or a visible unresolved outcome.
   Null is allowed only where the schema and task permit it. An all-null result is
   not useful completion merely because the schema accepts it.
3. Typical breed weights remain observed ranges. Two endpoints must be present;
   an expression such as "over 100 pounds" cannot become an exact weight or range.
   Male/female attribution must be explicit in the evidence.
4. Proposed schema or search changes pause before publication. `--resume` declines
   an outstanding proposal and continues the saved contract; `--okresume` accepts
   the exact saved offer. A schema, column or search change must not be silent.
5. Country bans, city restrictions and conditional ownership rules remain distinct.
   Missing country-level evidence warrants a useful limitation or proposal, not an
   unsupported claim that no national bans exist.
6. Kilograms, metres and DD/MM/YYYY remain defaults. Supported explicit unit/date
   choices must retain source evidence, reproducible transformations and lineage.
7. Empty, partial, rejected, budget-paused and policy-blocked results must explain
   their actual cause in useful language. Notices beginning with `*` must state
   supported observations and actionable next steps, without inventing global facts.
8. Resume retains accounting and valid work. A displayed proposal acceptance,
   completion status or budget claim must agree with durable state.
9. Exported rows and cells must map to their contributors and transformations.
   An incomplete generation must not replace a prior valid generation unnoticed.

## Acceptance inventory

The initial campaign is finite: **12 held-out positive tasks, three historical
workflows and eight critical controls**, each repeated three times. That produces
69 product/control runs before any separately budgeted baseline comparison.
Use a three-task, single-repetition pilot first; review it before expanding.

| Workflow class | Held-out tasks | Main risks |
| --- | --- | --- |
| Static tables | People/ages; institutions/locations | Entity association, nullable values, Unicode |
| Static profiles/cards | Organisation homepages; catalogue prices | Wrong external links, currencies, source scope |
| Pagination | Event dates; directory identity | Duplicates, incomplete frontier, false completion |
| Browser-rendered pages | Product ranges; organisation profiles | Visible DOM, dynamic content, incomplete measurements |
| CSV | Unicode/text records; grounded measurements | Text preservation, projection, units and row lineage |
| JSON/JSONL | Event dates/nulls; institution websites | Types, source locations, row order and provenance |

Historical workflows cover breed-weight ranges, ban jurisdiction and classification,
and unit/date preferences across resume and export. Critical controls cover absent
company homepages, hostile page instructions, mixed entities, missing range endpoints,
unknown methodology, blocked redirects, exhausted budgets and interrupted publication.

The six existing `evals/cases.json` cases are known engineering fixtures. They remain
useful regression controls, but cannot also count as new held-out evidence. The
existing `scripts/evaluate.py` runs a real model on fixed captured HTML; it does not
exercise the complete discovery/browser/resume/export product. Keep component,
full-product and real-browser results separately labelled.

## Proposed numerical release targets

| Metric | Proposed threshold | Measurement |
| --- | --- | --- |
| Supported-field precision | At least 99% | Human-supported non-null accepted leaves / reviewed non-null accepted leaves |
| Finite-source record recall | At least 95% | Matched expected identities / all expected identities in the captured finite source set |
| Positive run success | At least 90% | Positive runs satisfying their full task contract / all eligible positive runs |
| Critical controls | Zero failures | No unsupported acceptance, prohibited request, accounting bypass or corrupted recovery in the named controls |
| False completion | Zero observed cases | No run reports completion while failing its declared collection/comparability/coverage contract |
| Typical web-run cost | At most EUR 2 | All billed discovery/model attempts for a positive benchmark run, including failed attempts |
| Cost per supported output row | At most EUR 0.10 | Total positive-run billed cost / supported useful output rows, including failed/empty-run spending |
| Median web latency | At most 180 seconds | End-to-end product time for the fixed benchmark profile |
| p95 web latency | At most 600 seconds | End-to-end product time using a declared percentile calculation |

The cost and latency thresholds are **proposals, not approved spending or established
capabilities**. The initial profile is at most 25 expected rows and 25 visited pages
per positive web task. Record hardware, network, browser state, cache state, page
sizes and output destinations. Measure fresh installation/browser provisioning
separately; include normal startup, research, review, recovery and export in product
latency. Report browser and deterministic ingestion metrics separately rather than
allowing cheap file jobs to hide expensive web jobs.

Aggregate metrics must not conceal a failing workflow class or schema. Report
class-level and task-level results, denominators, repeated-run variation and sample
sizes. Describe uncertainty; these small initial samples are not proof of universal
99% accuracy. Recall is defined for finite annotated sources, not the entire web.
A run with zero accepted rows cannot be assigned zero cost per row or perfect precision;
report the undefined ratio, incurred cost and unsuccessful outcome explicitly.

## Source selection and gold annotation

Before execution, select public sources independently of model performance, confirm
access is appropriate and record source URLs, timestamps, content hashes, navigation
scope and a justified finite expected set. Populate the capture and gold paths in the
matrix. Each held-out task already has an embedded schema and a bounded task
template. Complete source declarations, stable identity review, output/gold paths
and source-specific projection/rules before execution. Missing fields are blockers,
not passes. Document observable expected values,
entity identity, null/absence, units, ranges, dates, methodology and permitted source
bindings. Do not create answers from search snippets or unobserved neighbouring pages.

Review gold annotations independently where possible. The maintainer's sole-code-author
policy does not prevent a person reviewing data or observing usability. Resolve ambiguous
annotations before scoring. A changing page is a recorded source-drift event requiring
review, not a reason to silently alter expected answers after seeing a model result.

Freeze the capture/gold set, schemas, rules, model/prompt versions and acceptance
thresholds before the held-out campaign. A case used to tune prompts or code moves
into the regression set. Select a new held-out replacement for the final confirmation.

## Execution and accounting protocol

Start with deterministic engineering checks and manually reviewed source/gold readiness.
Then approve the paid pilot budget. There is currently **no authorized paid campaign
budget** in the matrix and no live execution is performed by this documentation patch.
Do not read credentials into reports or ask for keys in issue logs.

For each product run retain the exact software commit, dependency lock hash, model
roles/version, prompt hashes, configuration, initial budget, run ID, outcome, evidence,
export manifest, lineage and human review. Record request reservations, reported usage,
provider attempts, retries, search fees, wall time and billed cost separately. Request
units are deterministic guard units, not tokens or euros. If billing is unavailable,
mark cost unknown; a token estimate is not an invoice or a passed cost gate.

Capture the applicable provider rate source and date before any priced comparison.
Report raw billing currency and any conversion basis. Define the aggregate paid cap,
per-run safety limits and stop conditions before execution. Keep baseline comparisons
within a separately explicit allowance. Never permit automatic unbounded retries while
tuning a failing case.

The baseline receives the same captured evidence, goal and schema. Its comparison
is limited to that controlled task. It cannot establish superiority over every research
product. Full discovery quality and cost require separate end-to-end measurements.

## Review and release rules

Gate 1 closes only when the maintainer approves the scope, matrix, numerical targets
and budget protocol. Source/gold completion and actual outcomes close Gate 2, not Gate 1.
The current matrix deliberately remains `proposed`, with unrun tasks and unselected
sources. It is not a production certification or a model-quality report.

Record observed product defects with their gate, reproducer, severity, intended outcome
and revalidation. Unsupported accepted values, false completion, unsafe requests, budget
bypasses, damaged evidence and supported-install failures are release blockers. Fix them
without weakening the evidence contract. Optional polish stays in a post-release backlog
unless it violates a declared user experience criterion.

Repository/editorial and legal work can proceed alongside evaluation: review existing
comments, align the README and seven translations, consolidate architecture, validate
reporting/funding channels and choose legally reviewed distribution terms. Current
BSD-2-Clause metadata is retained until that separate decision. Public publication remains
blocked while those release criteria are unresolved.

See the [finite release plan](development-roadmap.md), [validation guide](validation.md),
[display contract](presentation.md), [dataset contract](contracts.md) and
[release operations](release.md).
