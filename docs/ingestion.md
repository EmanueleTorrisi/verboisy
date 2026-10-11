<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Deterministic dataset parsing

## Explicit local and HTTP source modes

Local files and HTTP dataset endpoints use the same parser, projection, schema,
identity, observed-row evidence and immutable asset/export machinery. Source
selection is explicit; file contents cannot grant access to another directory or
change the network policy. The declared adapters support CSV, JSON, JSONL, TSV, plain text, DOCX and XLSX.
Arbitrary file bytes can be captured and indexed explicitly with `asset`. See
[File capabilities](formats.md) for the exact output, limitations and safety bounds.

### Local files

Configure absolute directory grants in the local `.env`:

```dotenv
DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
```

Then use a repeatable file declaration:

```bash
poetry run verboisy run --goal "Prepare the supplied people records" \
  --schema '[name]' --dataset-file 'json=/srv/verboisy-inputs/people.json' \
  --export people.json
```

CLI paths become canonical absolute `file:` URIs. Python/API and saved task
declarations use those URIs directly:

```python
from pathlib import Path
from verboisy import run
from verboisy.utils.config import Settings

source = Path("/srv/verboisy-inputs/people.json")
result = run(
    goal="Prepare supplied people records",
    schema=["name"],
    dataset_sources=[{"url": source.as_uri(), "format": "json"}],
    config=Settings(dataset_local_roots=[str(source.parent)]),
)
```

No directory is granted by default. The reader resolves paths before checking
directory membership, rejects remote file authorities and symlink escapes, and
accepts regular files only. It checks opened-file identity and changes during
capture. A local grant is an application policy for operator-controlled files,
not an operating-system sandbox against a hostile process with the same file
permissions. The operating system's access controls remain authoritative.

Captured source bytes, hashes and row locators persist in SQLite. Resume uses
those captured bytes even if a source moves, changes or is removed; it does not
refresh the acquisition silently. Uncaptured sources still require current grants.
Local declarations can be combined with HTTP declarations. Browser seeds cannot
be mixed into the declared-dataset workflow.

Deterministic local ingestion makes no model, search or browser calls. This does
not imply that every Verboisy research workflow is offline. It also does not
qualify gigabyte-scale inputs: current acquisition and replay defaults remain
16 MiB and 100,000 rows pending the streaming batch.

### Internal and authenticated HTTP endpoints

`--dataset-source json=https://internal.example/records` selects HTTP acquisition.
The endpoint must return a body that satisfies the ordinary dataset parser
contract. This adapter performs GET acquisition; provider-specific pagination,
POST queries, database drivers and OAuth login flows require separate adapters.

Place authentication headers in local configuration, not URLs or saved tasks:

```dotenv
ALLOW_PRIVATE_NETWORK=true
ALLOWED_DOMAINS='["internal.example"]'
DATASET_HTTP_HEADERS='{"https://internal.example":{"Authorization":"Bearer replace-locally"}}'
```

Credentials apply only to the exact scheme, host and effective port. A different
scheme or port is a different origin. Each redirect first passes source/network
policy, then resolves its own configured headers. Headers and server-issued
cookies are not carried implicitly between hops; an explicitly configured Cookie
header belongs to its own origin. Standard default ports are normalized. Keys
with paths, query strings or embedded credentials are rejected, as are headers
that override Host, compression, content length or connection framing.

HTTP header credentials are secret settings and are excluded from run tasks,
events and asset metadata. Captures still contain their observed source URL and
original data; local captures also identify their local path. Review the intended
data and metadata before sharing a bundle. TLS verification, DNS pinning, resource
limits and redirect checks remain active; this feature does not change public-web
network defaults or authorize arbitrary internal hosts.

### Qualification status

Offline regressions cover local grants, rejected paths/objects, byte limits,
file changes, CLI/API execution, immutable resume and portable evidence replay.
Real loopback HTTP tests verify acquisition with Authorization headers and
credential/cookie isolation across ports. Enterprise services and operating-system
deployment profiles still need their own acceptance evidence.

`verboisy.extractor.dataset.parse_dataset(content, dataset_format)` parses explicitly
supplied immutable bytes according to the [declared format contract](formats.md).
The textual table modes require UTF-8; Office modes read selected bounded OOXML
parts; `asset` indexes arbitrary bytes. The parser does not download sources,
call models, execute formulas, infer identity or project data into requested columns.
Public research runs use these same parsers through the source workflow below.

The result retains original bytes, their SHA-256 hash, parser version and immutable
source rows. Row values are copied on access. CSV rows retain one-based physical
start/end lines, including quoted multiline fields. JSON rows retain array index
pointers. JSONL rows retain physical line numbers; blank lines are skipped.

CSV headers must be unique and nonempty. Every data row must have exactly the header
width. CSV cells remain strings, including empty cells and formula-looking text.
JSON must contain an array of objects. Each nonblank JSONL line must contain an
object. JSON numbers and nulls retain their decoded types; duplicate keys and
non-finite numbers are rejected. A valid empty JSON array or header-only CSV has
zero rows and is not a claim of research completion.

Defaults limit input to 16 MiB, 100,000 rows and 32 nested container levels. Python's
CSV reader also enforces its field-size limit. Invalid UTF-8, malformed syntax,
NUL bytes, common HTML/XML signatures and ZIP/gzip signatures are rejected in
textual modes. DOCX/XLSX use their separate archive policy, and `asset` does not
interpret binary signatures.
A UTF-8 BOM is accepted while remaining part of the original bytes and hash.
Generic decompression, encoding inference, delimiter inference, archive extraction
to disk and semantic coercion are outside this parser version's supported contract.
The declared TSV delimiter and Office ZIP decoding are explicit parser operations.

## Bounded HTTP download

`verboisy.extractor.download.download_dataset` downloads an explicitly declared
format through a caller-supplied scope predicate. Every redirect destination is
checked before its request. Defaults permit five redirects and 30 seconds total;
byte, row and nesting limits match the parser defaults. Counts must be integers.

The HTTP client ignores ambient proxies, disables automatic redirects and requests
identity encoding. Compressed responses are rejected before reading their body.
Raw streamed bytes are checked against the byte limit even without a Content-Length
header; declared lengths must be nonnegative decimal integers and match the body.
Parsed modes require one of their registry media types; content still has to pass
the declared deterministic parser. Explicit `asset` mode permits any media type
while retaining acquisition limits and network policy.

The return value contains original/final URLs, the checked redirect chain, the
parsed bytes and hash, and bounded opaque Content-Disposition metadata. Remote
filenames are never used as filesystem paths. No asset file is written by this
version. Response streams close on errors and cancellation.

URL validation uses the existing network policy. Each new TCP connection resolves
and validates all returned addresses before connecting to a literal validated IP.
It does not resolve the original hostname again for that connection. Mixed public
and non-public DNS answers are rejected unless private access is explicitly enabled.
Fallback connects only to other addresses from the same validated set.

The HTTP hostname and TLS server name remain the original hostname. Certificate
and hostname verification are required; an incorrect certificate hostname fails
before any HTTP request. Ambient proxies remain disabled. The transport uses the
public HTTPCore backend and connection pool interfaces.

Loopback HTTP/TLS integration tests opt into private access. Their test certificate
and private key are fixtures only, valid for assets.example.test. Public internet and enterprise deployment qualification remain separate gates.

## Persistent dataset assets

`ResearchStore.save_dataset_asset(run_id, downloaded)` atomically stores an acquisition
and a `dataset_asset` event. `load_dataset_asset(run_id, asset_id)` and
`dataset_assets(run_id)` return verified immutable captures. They do not fetch sources
or call models. The store replays parser version 1 with its default byte, row and
nesting limits; larger custom-limit downloads are outside this storage contract.

Original bytes reside in SQLite BLOBs keyed by SHA-256. Each run has separate
acquisition IDs bound to its source metadata and captured rows. Identical bytes may
share a BLOB across runs, but loading an acquisition requires its owning run ID.
Original/final URLs, redirect chain, content type, opaque remote disposition, parser
version, headers, row values and physical lines or JSON pointers are retained.
Acquisition timestamps are assigned when the capture is first saved. No remote
filename becomes a filesystem path.

Repeating an identical capture is idempotent, including its event and timestamp.
Changed bytes or source metadata create a separate acquisition in capture order.
Bytes, metadata and parsed rows are checked on capture and replay; inconsistent
existing captures fail rather than being silently repaired or overwritten. This
is integrity verification, not verification that the source's claims are true.

Research database version 4 adds the asset tables. Existing version 2 and 3 databases
migrate on opening while preserving records, stable IDs, evidence, events and token
accounting. Older software cannot open version 4 databases; preserve a database
backup before opening a production database with the new version.

Capturing an asset does not accept its rows as research records or mark a run
complete. Projection into requested columns, row evidence and public run integration
follow separately.

## Declared dataset sources in public API runs

`arun` accepts declared sources in `task.dataset_sources`:

```python
result = await arun(
    goal="Read the published names",
    schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
    task={
        "dataset_sources": [{"url": "https://example.org/names.json", "format": "json"}],
        "target_records": 20,
        "identity_fields": ["/name"],
    },
    export="names.json",
)
```

This explicit API path accepts all eight declared modes in [File capabilities](formats.md). Declared dataset sources cannot
be combined with `task.seed_urls`. It does not run search, start Chromium or call a
model. Source host/path rules and the downloader's redirect/network rules apply.
Saved task declarations govern resume; callers cannot replace them during resume.
CLI `--dataset-source` and `--dataset-file` select this same deterministic path.

Rows enter the normal schema and identity checks with exact native source values.
CSV strings are not converted to numbers; fields are not renamed, dropped, invented
or semantically projected. Schema failures are retained as rejected candidates.
Empty strings and JSON numbers, booleans, nulls and nested leaves receive exact
JSON-value proofs. Browser snapshots cannot authorize dataset proofs. Each accepted
row snapshot binds its asset ID and one-based row index; `dataset_row` events add
physical lines or JSON row pointers. Row snapshots contain no fabricated HTML.

The source-step budget counts newly acquired sources per invocation. Saved assets
are verified and reused without consuming another download step. A capture can
retain more source rows than the requested accepted-row target; reaching that
target stops acceptance while retaining the full original asset. Resume reconciles
a snapshot-only interruption and a missing journal event after row acceptance.
Failed downloads may be retried on resume; malformed or corrupt saved assets fail
closed.

Completion still requires the ordinary target, schema, identity and comparability
checks. Source rows alone cannot establish missing unit, definition, methodology or
reference-period metadata. Unbounded or empty inputs do not claim completion.
Existing public ordering, IDs, JSON/CSV exports and proof reports operate on the
accepted rows. Exported evidence and events bind rows to asset IDs; original bytes accompany dataset captures in the portable asset sidecar described below.

## Portable original-asset bundles

Exports from runs with captured dataset assets add `<destination>.assets.json`.
The manifest's authoritative `asset_bundle` field names it and `files` includes
its SHA-256 checksum. Runs without dataset captures use `asset_bundle: null` and
retain the ordinary three checksummed dataset/evidence/event files. Format version
3 manifests remain additive; the asset sidecar has its own format version 1.

Each acquisition contains its stable ID, capture timestamp, source metadata, parser
version, headers, exact row values and locators, plus original bytes encoded as
base64. The decoded bytes retain their independent SHA-256 in dataset metadata.
All verified captures accompany the run, including unselected or rejected source
rows; source filenames are opaque metadata and never become output paths.

```python
from pathlib import Path
from verboisy.storage.asset_bundle import load_portable_assets

assets = load_portable_assets(Path("names.json.manifest.json"))
by_id = {asset.id: asset for asset in assets}
# An evidence snapshot's dataset_asset_id selects by_id[asset_id].
# Its dataset_row_index selects asset.download.dataset.rows[row_index - 1].
```

This reader needs neither SQLite nor a source server. It verifies the referenced
sidecar checksum, acquisition IDs, decoded bytes and row metadata against parser
version 1. Duplicate acquisitions, unsupported versions, malformed base64, metadata
mismatches, symlink sidecars and path traversal are rejected. Each input file is
limited to 256 MiB by default; `max_bundle_bytes` can explicitly change that limit.
The parser's per-asset byte, row and nesting limits still apply. The reader verifies
the asset sidecar; dataset, evidence and event checksums remain in `manifest.files`
for callers to check as well. Checksums establish integrity relative to the supplied
manifest, not authenticity or factual truth.

Output lineage maps sorted or grouped public rows to evidence record IDs. Dataset
row snapshots then identify the portable acquisition and source row; its locators
identify physical CSV/JSONL lines or JSON array pointers. Captured bytes can thus
be audited without the original database. Declared dataset runs report
`provenance: exact_dataset_values`, without claiming a model semantic review.

Captures are verified before replacing an existing export. The manifest is written
last and is absent if a sidecar write fails. Distinct export outputs cannot overlap
a dataset, manifest or sidecar, and new sidecars cannot overwrite database or
schema/task inputs. JSON and CSV exports may continue sharing their proof report.


## CLI declarations

Repeat `--dataset-source FORMAT=URL` for a declared format from `verboisy formats`:

```sh
verboisy run --goal "Collect names" --schema '[name]' --dataset-source 'json=https://example.com/names.json?version=1' --maxrows 20 --export names.json --proof
```

Formats must be exactly `csv`, `json`, `jsonl`, `tsv`, `text`, `docx`, `xlsx` or
`asset`. Quote URLs containing shell
metacharacters. Source order and query strings are preserved. The schema must
match exact source values; CSV cells remain strings. No browser, search or model
calls are made. Normal export defaults, identity and source policies apply.
`--max-steps` limits new source downloads. Resume with `verboisy run --resume RUN_ID`;
saved declarations are reused, so do not repeat `--dataset-source` on resume.
Python callers may use `dataset_sources`; conflicting task declarations fail.

## Explicit projection engine (R7a)

`verboisy.extractor.projection` provides a deterministic projection primitive.
Plans can be applied through declared-source ingestion or directly to captured
`SourceRow` objects. Sources without a plan retain exact-row ingestion:

```python
from verboisy.extractor.projection import ProjectionPlan, project_row

plan = ProjectionPlan.model_validate({
    "fields": [
        {"source": "/Person", "target": "/name"},
        {"source": "/Age", "target": "/years", "conversion": "integer"},
    ]
})
projected = project_row(asset.download.dataset.rows[0], plan)
values = projected.values
# Each projected.derivations entry records the source pointer, output pointer,
# explicit conversion, original JSON value and resulting JSON value.
```

Version `"1"` supports `identity`, `integer`, `number`, `boolean`, `string`,
`date_iso`, `date_dmy` and `date_mdy` (see explicit calendar date conversion below).
Identity copies the exact JSON value, including containers. Null stays null in
all conversions. Integer accepts JSON integers or text matching strict signed
integer notation; booleans, floating-point values, whitespace and leading zeros
are rejected. Text can yield arbitrary-size integers within Python runtime limits.
Number preserves existing finite JSON numbers and converts numeric text to a
float only when its decimal round-trip preserves the declared numeric value;
underflow, overflow and precision loss are rejected. Boolean accepts booleans or
exact text `true` / `false`. String preserves text and explicitly serializes
non-null scalar numbers and booleans using JSON notation. It rejects containers.
No locale, units, dates or field names are guessed, and formula text is never
executed.

Pointers use RFC 6901 escaping (`~0`, `~1`). Sources support object keys and
canonical array indexes; destinations create objects only. Root pointers,
malformed escapes, missing values, duplicate or overlapping destinations and
paths deeper than 32 components are rejected. A plan declares 1–100 fields;
unmapped source fields are omitted explicitly. Each result retains its source
row index, JSON array locator or physical CSV/JSONL line range. Result values are
independent copies; original bytes and parsed source rows remain unchanged.
Projection is atomic per row: an invalid field raises `ProjectionError` and
returns no partial result. Ingestion binds derivations to the immutable asset and validates each projected
record against its target schema.


## Projected ingestion (R7b)

Provide `--dataset-projection plan.json` alongside `--dataset-source`. For example,
use a JSON plan with the `Person` to `name` and `Age` to `years` mappings above:

```sh
verboisy run --goal "Collect people" --schema people-schema.json --dataset-source 'csv=https://example.com/people.csv' --dataset-projection plan.json --identity /name --maxrows 20 --export people.json --proof
```

The target schema must declare `years` as an integer. A simple column schema can
also be used. With `--strings`, each projected field must match the resulting
string schema; choose explicit string conversions where needed. Ordering and
other export shaping run after verified projection.
The Python API accepts `dataset_projection=plan` (a plan model, object or JSON file)
for all sources, or individual `projection` objects inside `dataset_sources`.
Conflicting common and per-source plans are rejected. Plans require declared
sources and cannot be supplied again on resume. Projection files are protected
from being overwritten by exports or their sidecars.

Original captured rows and bytes are preserved. Each projected snapshot contains
its declared plan, raw row JSON, immutable asset ID and source row index. Proofs
quote original source values, including numeric strings, rather than fabricated
converted text. The verifier independently replays the plan and checks the target
schema, identity and field rules. Invalid conversions are journaled as
`dataset_projection_failure`; invalid projected schemas remain rejected candidates.
Neither contributes to the target row count. Such runs pause with
`dataset_row_gaps` when no valid completion target is met. Resume uses captured
assets and saved plans, avoiding repeated downloads and duplicate failure events.

Both interrupted and completed dataset resumes validate accepted source bindings;
changed saved plans, snapshots or candidates fail the integrity check. Missing row
journals are restored only for interrupted runs. Completed validation is read-only.
Portable evidence and cell lineage explain each original source pointer and value,
its projection plan and resulting value before later normalization or export shaping.
Projected runs use `provenance: projected_dataset_values` and retain false truth and
global completeness claims. No browser, search or model calls are introduced.

## Bounded source profiles (R7c)

Declared-source ingestion journals one `dataset_profile` event for each captured
asset, before row projection or acceptance. It profiles original source fields,
including columns an explicit projection later drops. The event binds the asset
ID, original-byte SHA-256, parser version and profile version `"1"`. Existing
profiles are reused on resume, including when several projection plans reference
one capture. Completed resumes leave the journal unchanged. The checksummed
`.events.json` export includes these profiles for offline inspection.

The profiler uses the first 1,000 rows and the first 100 encountered JSON paths.
It visits containers and their children, preserving object/array/scalar type
changes at the same pointer. Each field reports present, missing and null row
counts, observed JSON types and distinct values within the sample. Distinct counts
use SHA-256 of canonical JSON, keeping strings, integers, floating-point numbers,
booleans and null distinct. These statistics do not establish global uniqueness,
entity identity, semantic compatibility or completeness. Prefix sampling can omit
later types or rare values; the sample policy and row/field truncation flags are
explicit. Empty rows contribute to missing counts but do not invent a root field.

At most three distinct examples per field are retained by default, each capped at
128 UTF-8 bytes. Truncated previews remain valid UTF-8, may be partial JSON text,
and have `truncated: true`; consumers must not treat them as complete values.
Each preview includes the source row index, which resolves its original value
and physical or JSON locator through the captured asset.
Pointers over 512 UTF-8 bytes are omitted and flagged separately. Exact original
values remain available in the captured asset. Unicode, formula text and URLs are
observed literally, with no evaluation or conversion.

```python
from verboisy.extractor.profile import profile_dataset

profile = profile_dataset(asset.download.dataset)
# Optional limits: sample_rows, max_fields, max_examples, preview_bytes.
```

Limits are validated against hard ceilings of 1,000 rows, 100 fields, five examples
and 1,024 preview bytes. Zero examples is supported. Frozen profile objects contain
immutable statistics and previews; raw captured rows are unchanged. Profiling
introduces no browser, search or model requests and makes no automatic mappings.

## Conservative mapping suggestions (R7d)

`verboisy.extractor.mapping` proposes explicit identity mappings from a bounded
source profile. Exact JSON pointers take precedence. When an exact pointer is
unobserved, a unique caller-supplied alias may be proposed. Alias declarations
use target pointers as keys and lists of source pointers as values; they are an
explicit caller decision, not inferred synonyms or name matching. Two observed
aliases remain ambiguous even when one happens to have a more convenient type.
An incompatible exact field is not silently replaced by an alias.

```python
from verboisy.extractor.mapping import suggest_mapping, validate_mapping
from verboisy.extractor.profile import profile_dataset

suggestion = suggest_mapping(
    profile_dataset(asset.download.dataset),
    target_schema,
    aliases={"/name": ["/Person"]},
)
# Review suggestion.decisions and suggestion.unmapped_profile_pointers.
plan = validate_mapping(asset.download.dataset, target_schema, suggestion)
# Apply this explicit plan through dataset_projection or --dataset-projection.
```

The immutable suggestion records exact/alias decisions, unresolved statuses,
unmapped observed paths, profile truncation, original asset hash, normalized
schema hash and mapping policy version `"1"`. Its `plan` property returns an
independent model only when every target field has a proposal. Missing sampled
values, incompatible types and unobserved pointers remain unresolved; a capped
profile cannot establish global absence. Nulls require a nullable target type.
Integers may map to a number field, while booleans remain a distinct type. Numeric
strings require an explicit conversion plan and are not automatically coerced.

Mapping traversal supports ordinary object properties, nested object properties,
whole array fields and array-of-object root schemas. Boolean field schemas,
untyped fields, references, conditional schemas and combinators remain explicitly
unsupported for suggestion; existing explicit projection and schema validation
remain available. Suggestion limits are 100 target fields, 32 path components and
8,192 UTF-8 bytes per target pointer. Alias lists are capped at 100 entries each.

A complete proposal is not acceptance. `validate_mapping` checks policy, asset
and schema bindings, then projects every captured row and validates the resulting
record against the authoritative schema. Later unsampled type changes, missing
fields, invalid dates, enum or numeric constraints, and incompatible array items
block validation. Empty captures cannot produce a validated plan. No date, unit,
currency, locale or semantic conversions are guessed; currency conversion would
require a separately declared policy with dated source rates. Normal ingestion
still enforces entity identity, evidence, schema and dataset completion rules.

This stage provides reviewable suggestions through the Python helper; ingestion
and the CLI do not automatically select or apply them. Validated plans use the
existing explicit projection path, preserving original bytes and source-bound
portable evidence. Suggestions and row validation introduce no model, search or
browser calls and do not establish external factual truth or semantic equivalence.

### Review mappings from the CLI

`verboisy map` works offline on an asset already captured in a saved research
ledger. Choose its run ID and find asset IDs with `verboisy assets` (below),
the exported assets sidecar, or the `dataset_asset` event. The target schema
comes from that saved run.

```sh
verboisy map --database research.db --run-id RUN_ID --asset-id ASSET_ID \
  --output mapping-review.json
```

The report contains the bounded raw-field profile, exact-pointer decisions,
ambiguities, unused fields, asset and schema hashes, and full-row validation
result. It creates a `dataset_mapping_review` journal event. It does not change
accepted rows, completion status or the saved run's projection policy.

For explicit aliases, supply a UTF-8 JSON object such as
`{"/name": ["/Name"]}` with `--aliases aliases.json`. Aliases represent your
chosen semantic relationships; compatible types alone do not prove meaning.

After reviewing the proposal, request a validated plan explicitly:

```sh
verboisy map --database research.db --run-id RUN_ID --asset-id ASSET_ID \
  --aliases aliases.json --output approved-review.json --plan projection.json
```

`--plan` records your approval request. A complete mapping that passes every
captured row is journaled as `approved` and written as a projection plan. An
unresolved or invalid mapping is journaled as `blocked`, writes its diagnostic
report, creates no plan and exits with code 2. A report-only invocation records
`proposed`, even when validation passes. Other errors exit with code 1.
Outputs must be new files in existing directories; inputs are not overwritten.
Use the plan with `verboisy run --dataset-projection projection.json` and the
same explicit dataset source in a new run. Approval does not silently revise an
existing run. Journal events enter the portable events sidecar on its next
export; previously written bundles are unchanged.

### Explicit calendar date conversion

Projection fields support three additional, explicit conversion modes:

| Conversion | Required source notation | Example | Output |
| --- | --- | --- | --- |
| `date_iso` | `YYYY-MM-DD` | `2024-02-29` | `2024-02-29` |
| `date_dmy` | `DD/MM/YYYY` | `03/04/2025` | `2025-04-03` |
| `date_mdy` | `MM/DD/YYYY` | `03/04/2025` | `2025-03-04` |

These modes require ASCII digits, exact zero padding and separators, and a valid
Gregorian calendar date with year 0001–9999. Nulls remain null. Invalid calendar
values, whitespace, timestamps, numbers and other notations fail explicitly;
the original row and bytes remain captured. Schema validation still applies to
the result, including a declared JSON Schema `format: date`.

```json
{"version":"1","fields":[
  {"source":"/observed","target":"/date","conversion":"date_dmy"}
]}
```

Use this explicit plan with `--dataset-projection`. Mapping suggestions keep
identity conversion; they do not infer a date format. The declared mode is
persisted in the run policy, replayed independently during evidence validation,
and included in each converted cell's projection lineage. Existing version-1
plans retain their behavior. These modes convert calendar dates, without time
or timezone interpretation.

### Review a caller-declared conversion plan

To review a plan containing explicit conversions, pass its JSON file to
`verboisy map --projection`. For example, a plan with `date_dmy` and `integer`
conversions can be reviewed and approved as follows:

```sh
verboisy map --database research.db --run-id RUN_ID --asset-id ASSET_ID \
  --projection supplied-projection.json --output conversion-review.json \
  --plan approved-projection.json
```

The input file must contain exactly one JSON projection-plan object and be at
most 1 MiB. `--projection` and `--aliases` are mutually exclusive. The report's
`proposal_kind` is `declared_plan`; its decisions identify the caller's pointers,
and its captured plan retains every declared conversion. It does not apply the
sampled type filter used for automatic suggestions: instead, every captured row
must pass the declared projection and authoritative schema. Thus explicit safe
coercions and complex schemas remain usable, while failed conversions or schema
checks block approval. The original input file is protected from output writes.

Omit `--plan` to write a proposal report only. Include it to request approval;
blocked requests create a report and journal entry but no approved plan. Apply
an approved plan explicitly with `run --dataset-projection` in a new run.


### Inspect captured asset identities

```sh
verboisy assets --database research.db --run-id RUN_ID --limit 100
```

This command prints a JSON inventory for the specified saved run, including
completed runs. Each listed capture includes its asset ID, acquisition time,
original and final URLs, byte hash, format, parser version, byte count and row
count. Use an `asset_id` from this output with `verboisy map --asset-id`.

The inventory lists captures in acquisition order and verifies each listed
capture's persisted bytes and metadata before printing. Inspection uses no
network, browser or model requests and does not add journal events, change
accepted rows, alter completion status or consume request budgets. A run with
no captures produces an empty inventory. Unknown runs and corrupt listed
captures fail with exit code 1, without printing a partial JSON inventory.

`--limit` defaults to 100 and accepts integers from 1 to 1000. If more captures
exist, `truncated` is true; captures beyond that limit are not inspected or
represented. Raise the limit when appropriate. The supplied database must
already exist; inspection does not create a new ledger for a mistyped path.

Inventory reads use a read-only SQLite connection and a consistent transaction
snapshot. They require the current ledger version and do not initialize an
empty database or migrate an older one. A saved run can be inspected while the
normal store's writer lock is held; only committed captures are visible.

### Grounded dataset unit derivations

`project_unit_value` provides a deterministic derivation helper for explicitly
chosen value and unit columns in a captured `SourceRow`:

```python
from dataclasses import asdict
from verboisy.extractor.unit_projection import project_unit_value

result = project_unit_value(asset.download.dataset.rows[0], "/amount", "/unit")
normalized = result.value
provenance = asdict(result)
```

The complete unit label must occur as the value of the declared unit pointer in
the same row. The helper reuses the existing recognized labels for counts of
people, mass in grams and length in meters, including their supported scales.
It converts only to that unit's canonical base; it does not infer units from
field names, numeric magnitude or another row. Unknown, compound and ambiguous
labels remain explicit errors. Currency labels are not supported by this helper.

JSON numbers and strict JSON numeric text are supported. Integer arithmetic is
exact, including numeric text beyond float precision. Float results must remain
finite and exactly preserve the decimal value represented by the source number;
rounded or non-finite results fail. Large integral results remain exact
integers. Null remains null when its unit is grounded.
The frozen derivation records the original typed JSON value, observed label and
canonical units, value/unit pointers, normalized JSON value, row locations and
policy version. Original bytes and source rows are unchanged; repeated calls
derive from the original value rather than applying a scale twice.

### Declared unit conversion in projection plans

Declare the numeric source and its same-row unit column explicitly:

```json
{"fields": [{"source": "/amount", "target": "/population", "conversion": "unit_base", "unit_source": "/unit"}]}
```

The ingestion workflow applies this plan to captured original rows. Independent
verification replays the conversion and checks the auxiliary unit source label.
Unknown labels or invalid arithmetic leave row gaps. Existing plans retain their
serialized form and resume identity.

Fields declared `x-verboisy-unit-sensitive` and
`x-verboisy-comparable-across-rows` use the grounded canonical units for completion
checks. Different dimensions block completion; different scales of the same
base unit remain comparable. Projected values are not scaled again by legacy
normalization events. Definition and methodology requirements remain separate.

Exported scalar cell lineage includes `unit_derivation`, with the original
numeric value, observed unit label, both source pointers, canonical unit,
normalized value and physical source-row locations. The captured asset remains
unchanged. These derivations establish the conversion, not external truth.

### Grounded definition and methodology descriptor helper

`project_descriptor` binds a captured field value to an explicitly selected
label column in the same source row:

```python
from dataclasses import asdict
from verboisy.extractor.descriptor_projection import project_descriptor

result = project_descriptor(
    asset.download.dataset.rows[0],
    "/population",
    "/population_definition",
    kind="definition",
)
provenance = asdict(result)
```

Use `kind="methodology"` for an explicitly declared methodology label. Both
pointers follow the existing JSON pointer rules, including escaped names and
canonical array indexes, with a maximum depth of 32. Missing columns, nontext
or whitespace-only labels and labels longer than 500 characters fail explicitly.
Labels must be valid UTF-8 text. The helper retains their exact case, whitespace,
punctuation and Unicode; it neither evaluates formula text nor treats different
labels as equivalent.

The frozen result preserves the original typed JSON value, exact label and
label JSON, both pointers, descriptor kind, source row locations and policy
version. Null field values remain null. Repeated calls replay the captured
source row without changing original values or bytes. A label establishes its
presence and declared association with a field; it does not establish source
quality, authority, semantic correctness or the truth of the field value.

The helper is also used by the declared projection bindings below.


### Declared descriptor bindings in projection plans

Attach descriptors to the scalar field whose source value they describe:

```json
{
  "fields": [
    {"source": "/name", "target": "/name"},
    {
      "source": "/amount",
      "target": "/population",
      "conversion": "unit_base",
      "unit_source": "/unit",
      "descriptors": [
        {"kind": "definition", "source": "/population_definition"},
        {"kind": "methodology", "source": "/population_method"}
      ]
    }
  ]
}
```

Descriptors work with ordinary scalar conversions as well as `unit_base`.
Each field may declare one definition and one methodology binding. Duplicate
kinds, container targets, missing columns or invalid labels fail projection
atomically and leave a row gap. Metadata columns need not appear in output rows.
The mapping review command accepts these explicit plans through `--projection`;
`--plan` writes an approved plan for a new run, preserving the original run.
Existing plans without descriptors retain their serialized form and row identity.

Independent evidence verification replays the original captured row and checks
each auxiliary label's exact JSON text, source scope and text-source kind.
Schema fields that require `x-verboisy-definition-sensitive` or
`x-verboisy-methodology-sensitive` together with
`x-verboisy-comparable-across-rows` use the declared grounded labels for literal
comparability. Differing labels block completion. Undeclared requirements remain
unknown even if a similarly named metadata column happens to exist. Descriptor
bindings do not supply unit metadata or source quality assessments.

Exported scalar cells include `descriptor_derivations` with exact labels,
original typed values, both pointers, descriptor kinds and captured physical row
locations. Grouped cells retain each contributor's descriptor derivations.
Completed resume validates saved source bindings and replays offline, preserving
original asset bytes and the journal. Labels establish declared literal
associations, not semantic equivalence or external factual truth.

### Grounded reference-year helper

`project_reference_year` associates a captured value with an explicitly selected
reference-year column in the same source row:

```python
from dataclasses import asdict
from verboisy.extractor.temporal_projection import project_reference_year

result = project_reference_year(
    asset.download.dataset.rows[0], "/population", "/reference_year"
)
provenance = asdict(result)
```

The selected year must be an integer from 1000 through 9999 or text containing
exactly four ASCII digits in that range. This matches the existing reference-year
proof range. Boolean values, decimals, nulls, surrounding whitespace, Unicode
numerals, dates, ranges, fiscal-year notation and prose fail explicitly. A
publication date or a different row's year cannot fill a missing declared column.
Selecting the column declares its reference-year role; the helper does not infer
that role from the column name or assess the source's authority.

The frozen derivation preserves the original typed field value, exact typed year
JSON, parsed reference year, both pointers, source row locations and policy
version. Null field values remain null. Pointers use the existing JSON pointer
rules with a maximum depth of 32. Original source bytes and values remain
unchanged, and repeated calls replay them. Different years produce different
derivations even when the field value is unchanged.

The helper is also used by the declared reference-year bindings below.


### Declared reference-year bindings in projection plans

Add `reference_year_source` to a scalar field declaration:

```json
{
  "fields": [
    {"source": "/name", "target": "/name"},
    {
      "source": "/amount",
      "target": "/population",
      "conversion": "integer",
      "reference_year_source": "/reference_year"
    }
  ]
}
```

The binding works with ordinary scalar conversions, `unit_base`, and descriptor
bindings. It does not require the year column in the output schema. Mapping
review recognises the selected year column as a used input. Old declarations
retain their serialized form and source-row identity.

Ingestion creates a temporal proof bound to the exact original year JSON.
Independent verification replays the captured row and requires the selected
text source, same-row scope, exact quote, parsed year and declared output pointer
to agree. Missing or invalid year columns cause projection gaps. Extra temporal
proofs on projected rows are rejected rather than accepted as inferred periods.

Existing field semantics and temporal intent govern these proofs. Requested-year
or range mismatches and future years under latest intent are rejected. Comparable
snapshot-like fields with different years block completion; time-series and event
fields retain their existing multi-period policy. Declaring a year does not
classify field semantics or change the identity replacement policy.

Exported scalar cells include `temporal_derivation` with the original typed field
value, raw year JSON, parsed year, both pointers and physical source-row locations.
Grouped cells preserve each contributing temporal derivation. Completed resume
validates captured asset bindings and reconstructs the same proofs offline.
These bindings record the caller-declared reference period without establishing
source authority or external factual truth.

### Temporal refresh for declared dataset identities

Processed dataset observations now use the existing candidate comparison and
atomic replacement machinery when identity fields are explicitly declared.
For fields with an explicit temporal intent, that intent governs ordering. A
mutable or slowly changing field with a required reference period can use the
run's temporal intent when no field-specific intent exists. Event, time-series
and unresolved field classes are not assigned an implicit latest replacement
policy. Historical requests retain their existing period checks.

A provably newer candidate can replace an accepted identity, including when its
values are unchanged. Its stable record ID remains unchanged; the accepted
evidence and exported lineage bind to the replacement source row. Older
observations remain stale or duplicate evidence. Same-period value disagreements
retain the existing unresolved identity-conflict behavior.

Replacement must preserve prior temporal bindings, canonical unit dimensions
and exact definition/methodology labels. A newer year does not justify dropping
or changing that metadata. Such attempts keep the current record and journal
`blocked_reason: metadata_regression` with the comparison. This checks literal
metadata preservation, not external source authority.

The target counter uses actual accepted entity records, so replacing a row does
not count as another entity or stop the run prematurely. Comparisons are
journaled and candidate supersession preserves the existing atomic storage
history. Resume replays saved assets without redownloading or repeating processed
comparisons. Only processed observations participate; the existing source and
record target bounds still determine when ingestion stops.

### Repairing required dataset metadata on repeated identities

A processed repeated identity may now replace its accepted evidence when the
entire output record is unchanged, including JSON value types, and the later
projection supplies a previously missing required unit, definition or methodology
binding. The binding must be independently replayed from its captured source row;
field semantics must explicitly require that metadata. Optional metadata alone
does not cause replacement.

Every existing temporal binding must retain its reference year, and every
existing canonical unit and exact descriptor label must be preserved. A repair
cannot change a claim, drop metadata, change its meaning or bypass evidence
verification. Temporal disagreements retain the existing comparison policy.
Successful repairs journal `comparison_mode: dataset_metadata_repair`, use atomic
candidate supersession and preserve the stable record ID. Exported evidence and
cell lineage point to the replacement row; completed resume verifies it offline.
The existing source and entity target limits still apply, so only observations
processed within those bounds can repair a record. No metadata is inferred and
these literal bindings do not establish external factual truth or source authority.

### Repair scanning after reaching an entity target

For datasets with explicitly declared identity fields, reaching `maxrows` no
longer ends ingestion while required dataset consistency gaps remain. Remaining
rows and declared sources can supply repair evidence for already accepted
identities. Rows whose identities are not currently accepted are journaled as
`skipped` with `entity_target_reached` and do not enter the candidate or conflict
ledger while the entity target is full. A successful replacement retains the
stable ID and does not increase the entity count.

Scanning stops when the required consistency gaps are resolved. Without declared
identity fields, the entity target retains its original stopping behavior.
Download-step limits, per-file limits, scope checks and the run timeout remain
in force. A download budget pause can resume using captured assets without
redownloading or repeating processed rows. Exhausting all declared repair rows
without resolving the gaps still leaves the run incomplete; no search or model
request is introduced by repair scanning.

### Repairing a missing required reference year

An equal-valued repeated identity can now repair a missing reference-year binding
for a non-static field whose semantics require both a reference period and
comparability across rows. The year must come from the declared same-row
projection and pass independent source replay and the run's temporal policy.
Future years for latest requests and years outside an explicit requested period
cannot repair the accepted record.

The entire typed output record and every prior year, canonical unit and exact
definition/methodology label must be preserved. Optional periods, static fields
and fields without cross-row comparability do not trigger this repair by
themselves. Successful repairs use `dataset_metadata_repair` comparisons and
atomic supersession, retaining the stable record ID and entity count. Accepted
proofs and portable cell lineage then bind to the dated source row. Existing
bounded repair scanning and offline resume apply; a rejected year leaves the
required-period gap unresolved.

### Current repair diagnostics in results and exports

Dataset API results expose `dataset_consistency` with `scope: accepted_records`,
current `gaps` and the existing planner's `repairs`. The CLI prints each current
gap and each planned repair's stable record ID, pointer and reason. Export
manifests contain the same diagnostic snapshot. These IDs refer to accepted
internal evidence records, including when public exports are sorted or grouped.

Diagnostics are recomputed from current accepted evidence, rather than copied
from old gap events. After a successful repair, resumed results and manifests
therefore show cleared gaps and repair requests. Reporting performs no discovery,
model request or journal mutation. A gap without a planner request remains
visible; the report does not infer a target period without a supported run
or field-specific intent.

For non-dataset API runs and direct exports without supplied evaluated
consistency diagnostics, the field is `null`, rather than claiming evaluation.
Extension metadata cannot overwrite this authoritative manifest field. These
diagnostics describe the accepted collection and do not establish external
truth or global completeness.

### Period repair planning for declared dataset sources

For explicitly declared dataset sources, a required mutable or slowly changing
field can use the run's temporal intent when no field-specific intent exists.
This matches dataset refresh ordering and allows missing-period repair requests
for latest and exact-year goals. Explicit field intent takes precedence; planning
uses a copy and does not alter the saved field semantics.

Latest requests may leave `target_year` unset when no accepted period is known.
For mixed snapshot vintages, the existing planner targets the latest observed
period and requests repair only for older records. Exact-year requests retain
the requested year. Static, event, time-series, unresolved and optional-period
fields receive no implicit policy. A range request is not narrowed to an inferred
single year. Browser research keeps its existing field-scoped planning behavior.

Dataset temporal requests include the current accepted candidate key and snapshot
ID alongside the stable record ID and pointer. API results and manifests expose
these requests, and they disappear after successful repair. Creating the request
does not fetch another source, spend provider budget or change the journal.

### Inspect saved repair needs without resuming

```bash
verboisy repairs --database path/to/research.db --run-id RUN_ID --limit 100
```

This command reads a coherent SQLite snapshot in read-only mode. It requires an
existing current-version ledger and a run with declared dataset sources. It
verifies captured asset bytes and accepted row bindings before returning JSON
with the saved status, stop reason, current accepted-record gaps and planned
repairs. It neither resumes ingestion nor performs migrations, journal writes,
downloads, search, model requests or browser navigation. It can inspect a saved
snapshot while the single-writer lock is held.

`--limit` ranges from 1 to 1000 and bounds the returned repair list. `repair_count`
reports the full number of planned requests; `truncated` indicates omitted
requests. Gaps still describe all accepted evidence, so a truncated repair list
must not be interpreted as the whole repair plan. Altered captures or accepted
bindings cause inspection to fail. Inspection does not infer source authority,
external truth, or global collection completeness.

### Finding saved runs

Run `poetry run verboisy runs` to list up to 100 recent runs from the existing
configured `SQLITE_DB_PATH` (default `verboisy.db`). Use `--database` to select
another ledger and `--limit` (1–1000) to bound the list. The JSON report includes
the actual database path, run IDs, goals, statuses, stop reasons, declared dataset
source counts and whether more runs were omitted. Runs are ordered by creation,
most recent first.

`repair_inspection: "available"` means the saved task has declared dataset
sources; it does not claim that captured evidence is valid or repairs are needed.
`no_dataset_sources` marks browser-only runs; `invalid_task` marks an unreadable
saved task without hiding other runs. A failed or paused run may still be eligible.
Copy an eligible `run_id` into `verboisy repairs --database <reported-database>
--run-id <run-id>`. Repair inspection independently verifies captured evidence.

Run inventory uses a coherent SQLite read-only transaction, including while a
writer holds the application lock. It performs no migration, creates no database
or lock file, and makes no browser, model or download calls. Older ledger versions
must be migrated separately before inspection.

### Browser proposals with nullable fields

Extraction prompts distinguish required property presence from non-nullability.
An unknown required field that permits null is represented as null without
fabricated evidence; a missing required non-nullable value prevents the proposal.
Numeric facts require numeric transforms and exact observed literals. Ranges or
combined-sex weights do not justify separate point estimates.

The prompts include examples of exact string quotes, observed source IDs, entity
scope and claim meaning. Restrictions or ownership conditions do not by themselves
establish bans; a city statement does not establish a countrywide statement.
These instructions guide proposals and review; deterministic verification and
semantic rejection remain authoritative. Prompt changes do not establish that a
particular page contains qualifying records or that live extraction will succeed.
