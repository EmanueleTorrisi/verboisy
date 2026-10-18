<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# CLI reference

The normal interface is designed around a goal, a simple schema, and one or more exports.

```bash
verboisy run \
  --goal "Find white laptops under €1000" \
  --schema '[name,brand,color,price,screen_size]' \
  --export laptops.csv
```


## Research and source policy

### Basic

`--goal TEXT` describes the dataset to research.

`--schema TEXT` accepts either a simple list such as `[name,price,website]` or a JSON Schema file path.

`--export PATH` writes CSV or JSON. Repeat it to write multiple formats.

`--strings` forces simple-schema fields to `string | null`.

### Source control

`--include DOMAIN` adds a domain-specific discovery query. It may be repeated.

`--avoid DOMAIN` excludes a domain from discovery and traversal. It may be repeated.

`--onlyinclude` restricts browsing to the domains passed with `--include`.

### Research

`--research` expands traversal depth, page limits, and link breadth. It is intentionally incompatible with `--maxrows`, ordering, grouping, and SmartID in this release.

This mode can use substantially more browser requests, search requests, model tokens, time, and provider budget.

### Advanced

`--task PATH` loads the existing advanced TaskSpec configuration. Advanced JSON Schema and task policies remain the lower-level contract used by the same research engine.

### Explicit entity identity

Use `--identity` with a row-relative JSON pointer to a scalar field in the requested
schema. Repeat the option for a compound key:

```bash
verboisy run --goal "Find inventory items" --schema '[namespace,sku,price]' \
  --identity /namespace --identity /sku --export inventory.json
```

The Python API accepts `identity=["/namespace", "/sku"]`. These declarations use
the existing `task.identity_fields` mechanism and are saved with the run. A
conflicting task declaration is rejected. Resume reuses the saved key; passing
identity options on resume is rejected.

Choose keys whose uniqueness is justified in the source domain. A name alone is
not generally unique. Every identity field needs supported, nonempty scalar data;
missing or null identity values fail candidate verification. Use JSON Pointer
escaping (`~1` for `/`, `~0` for `~`) in field names. Nested object fields are
supported; array wildcard keys are rejected. At most 20 distinct pointers may be
specified. Public sequential row IDs are separate from these entity keys.

Without a declared key, existing whole-record identity behavior is retained.
Changed observations can count as separate rows; this option does not infer keys
or establish that unkeyed rows represent distinct entities.

### Search attempt budget

Set `SEARCH_REQUEST_BUDGET` to a nonnegative integer to limit search attempts per saved run.
The default is unlimited; `0` blocks provider search before network access. This limit
counts OpenAI and Brave attempts, including retries, fallback, failed requests and
cancellation. Reservations persist in the search journal and resume retains them.
Increase the limit to continue a paused run. The stop reason is `search_request_budget`.
This is separate from `MODEL_REQUEST_BUDGET`, which measures conservative model request
units. An attempt reservation does not establish that the provider billed the request.
Standalone low-level search calls have no durable run ledger; use the public API or CLI
for a cumulative limit. Historical unjournaled requests cannot be counted retrospectively.


## Output shaping and display

### Dataset shaping

`--maxrows N` sets the desired accepted-record ceiling.

`--orderby FIELD` sorts ascending. It may be repeated.

`--orderbydesc FIELD` sorts descending. It may be mixed with `--orderby`.

Argument order defines priority:

```text
--orderby age --orderbydesc height --orderby name

1. age ascending
2. height descending
3. name ascending
```

`--groupby FIELD` groups rows, deterministically aggregates numeric fields, then applies surviving sort keys.

### Dataset relationships

`--smartid PATH` loads a previous Verboisy CSV or JSON dataset and attempts a conservative relational match. The new relation column is derived from the dataset name, for example `people.csv` to `person_id`.

Ambiguous relationships become `null`.

### Output and proof

`--proof` writes a `*.proof.txt` report derived from persisted run state. At least one `--export` is required.

Each CSV or JSON export also receives:

- `*.evidence.json`
- `*.manifest.json`

### Observed ranges in numeric columns

Browser extraction can now report an optional `range_conflicts` list with a field
pointer, entity scope, observed source ID and literal interval. Verboisy grounds
each signal against the supplied source before offering a change. It also checks
numeric proofs that quote an interval, including up to 100 saved rejected
candidates at resume. Saved-candidate inspection makes no browser, search or
model requests and does not reset accounting.

For eligible top-level numeric columns, an observed complete interval can pause
the run with `*` notices before semantic reviews, further extraction or export.
The offer changes only the affected column types to strings, preserving nullability
and other requirements. Inspect its complete replacement schema and supporting
quotes with `verboisy changes --run-id RUN_ID`. Accept with `--okresume RUN_ID`,
or decline with `--resume RUN_ID`. A declined replacement contract is not
automatically reoffered merely because another page repeats the same evidence.

The notice describes the cited sources; it does not claim that all sources report
ranges or that a point estimate cannot exist. Numeric min/max columns remain an
alternative schema for a new run. Point estimates and lower bounds such as
"over 100 pounds" are not converted into complete intervals. Identity columns,
nested fields and numeric fields with explicit constraints or mappings are not
automatically rewritten. Units are preserved as printed, not inferred or converted.
Accepted range strings still require exact quotes and independent semantic review.
Preferred-unit conversion and date presentation are implemented display features. All typed extraction proposals are now retained in the
event ledger, including the complete proof objects, before verification.


Automatic alternatives can also propose a replacement research goal and add, drop or
change columns when checked source text supports a specific alternative. The `*`
notice lists the proposed goal and column changes; `verboisy changes --run-id RUN_ID`
shows the exact replacement schema and cited quotes. `--resume` declines the offer;
`--okresume` accepts it. Acceptance revisits the saved browser frontier under the new
requirements, preserving the run's source restrictions, task settings and consumed
budget. It does not reset the budget or guarantee a fresh search-provider query.

These broader offers use the existing extraction response, without a separate model
call. They are considered only after a batch has no qualifying candidate, for browser
runs with no accepted rows. Identity columns and columns with explicit field rules
cannot be changed automatically. A cited quotation supports considering an alternative;
it does not prove that the original goal is impossible worldwide. Offers are currently
created during new page processing; older saved candidates can still produce the
numeric-range offers described above. Units and date display preferences are separate
features and are not changed by this workflow.

Display preferences are independent of saved research requirements:

```bash
verboisy run --resume RUN_ID --mass-unit lb --length-unit ft --date-format mdy
verboisy run --resume COMPLETED_RUN_ID --date-format iso --export rows.json
```

Defaults are `--mass-unit kg`, `--length-unit m`, and `--date-format dmy`.
Mass supports `kg`, `lb`, or `source`; length supports `m`, `ft`, or `source`;
dates support `dmy` (DD/MM/YYYY), `mdy` (MM/DD/YYYY), `iso`, or `source`.
Set new-run defaults with `VERBOISY_MASS_UNIT`, `VERBOISY_LENGTH_UNIT`, and
`VERBOISY_DATE_FORMAT` in `.env` or the process environment. Inspect them without
opening a ledger or calling a provider:

```bash
verboisy presentation-config
```

Explicit run flags override saved preferences. Saved preferences override configured
defaults, so changing `.env` does not silently change a resumed run. Defaults fill
unsaved choices; built-in defaults apply when configuration is omitted.
Python `arun`/`run` accept `mass_unit`, `length_unit`, and `date_format` as explicit
overrides. `Settings(display_mass_unit=..., display_length_unit=...,
display_date_format=...)` supplies defaults. See [Display preferences](presentation.md)
for the supported vocabulary, precedence examples and conversion limits.

Completed runs export from the saved ledger without new browser/model work.
Resuming an incomplete run also continues its pending research; these flags do not
turn an incomplete run into an export-only invocation. They do not accept a pending
research proposal: use `--okresume` explicitly for that decision.

The presentation layer converts complete scalar or range strings carrying an
explicit recognised mass/length unit. A range needs two observed endpoints. Unknown
units, lower bounds and numbers without unit context remain unchanged. Bare `m` and
`in` require the field annotation `"x-verboisy-dimension": "length"` because those
abbreviations have other meanings. Conversions round to six decimal places; original
precision and wording remain in evidence.

Numeric mass and length cells also convert when the accepted snapshot supplies a
verified unit binding, or a declared dataset unit projection can be replayed.
Column names and model guesses do not establish units. Prior normalization is
replayed before choosing the effective source unit, preventing double scaling.
Numeric columns remain numeric; `--strings` columns remain strings. Grouped cells
convert only when every contributor has the same verified effective unit. Unknown,
missing, conflicting or stale unit bindings leave values unchanged.

Each successful numeric display step records its source unit, target unit, original citations or
projection pointers, and six-place rounding policy in portable cell lineage. This
includes zero and unchanged values when finite display arithmetic succeeds. Extremely
large or unrepresentable fractional results remain unchanged without a target-unit claim. `source`
retains the effective ledger value, which may already be normalized to grams or
metres; it does not undo an accepted normalization. Exported numbers carry their
units in the manifest rather than an added unit column. Original evidence is unchanged.

Date formatting requires a field schema with `format: date` or `format: date-time`
and a valid ISO source value. Ambiguous dates are never guessed. Date-time offsets,
clock time and fractional seconds are preserved; no timezone conversion occurs.
Identity fields remain unchanged. Sorting, grouping and smart-ID matching precede
presentation. Each formatted cell includes a portable `presentation` lineage step.
The manifest retains the original extraction schema: formatted dates may therefore
make `collection_schema_valid` false, even though accepted source records were valid.
Display preferences, source values and output values remain separately inspectable.


## Providers and request contracts

### Provider failure diagnostics

Future failed model requests include their HTTP status and, when recognized,
structured provider error codes and parameter names. HTTP 400 diagnostics identify
model compatibility checks for `max_tokens`, `temperature` and JSON
`response_format`; HTTP 401, 403 and 404 point to credentials, permissions and model
or endpoint configuration respectively. These are troubleshooting hints, not a
claim that a particular setting caused the failure.

Only a fixed set of known code and parameter identifiers is included. Raw provider
messages, response bodies, request prompts, URLs and credentials are not copied
into these failure messages. Retry and request budget policies are unchanged, and
no automatic parameter substitution is performed. Previously saved generic errors
remain unchanged; their missing provider details cannot be reconstructed locally.

### Explicit model token-limit parameter

`LLM_TOKEN_LIMIT_PARAMETER` selects the Chat Completions keyword sent through
LiteLLM. Its accepted values are `max_tokens` (the backward-compatible default)
and `max_completion_tokens`. `MAX_TOKENS` remains the positive numeric ceiling
for either choice; exactly one token-limit keyword is sent on each attempt.

For a provider/model that requires the latter keyword, configure:

```dotenv
LLM_TOKEN_LIMIT_PARAMETER=max_completion_tokens
MAX_TOKENS=4096
```

The [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create/)
defines `max_completion_tokens` as including visible output and reasoning tokens.
Select the keyword for your provider and model; this setting does not establish
compatibility with temperature, JSON response format or other request fields.
It applies to all model roles sharing the Settings instance, including explicit
model overrides. Mixed-provider configurations must use a keyword supported by
each configured role. Invalid choices are rejected during configuration loading.

Conservative request reservations still use UTF-8 message bytes plus `MAX_TOKENS`;
reported provider usage, retry limits, credential routing and JSON validation are
unchanged. A rejected request is not automatically retried with a different
keyword. OpenAI Responses-based search retains its own `max_output_tokens` field.

### Explicit temperature omission

`LLM_SEND_TEMPERATURE=true` is the default: model requests include the validated
`TEMPERATURE` value. Set `LLM_SEND_TEMPERATURE=false` to omit the keyword entirely
when your provider/model requires omission. This sends neither a numeric value
nor JSON null; the provider applies its own default. `TEMPERATURE` remains
validated between 0 and 2 even when omitted.

The choice applies to all Chat Completions model roles and explicit model
overrides using the same Settings instance. It can be combined with either
`LLM_TOKEN_LIMIT_PARAMETER` choice. It does not establish compatibility with the
selected model's other request fields. There is no automatic fallback that drops
temperature after a rejected request. Retry behavior, JSON response validation,
credential routing and budget accounting remain unchanged. Responses-based
search is unaffected.

To explicitly omit temperature:

```dotenv
LLM_SEND_TEMPERATURE=false
```

### Inspecting active model configuration

Model-specific [provider profiles](providers.md) can select separate endpoints,
credentials, output allowances and JSON modes for different role models. Existing
settings remain the fallback when no profile matches.

Run `verboisy model-config` before a provider retry to inspect settings
loaded from the current environment and `.env`. The JSON report lists the default
model and each role's effective model, selected token-limit keyword and ceiling,
whether temperature is sent, its effective numeric value when sent, configured
request budget, effective budget ceiling, retry count, request interval and timeout.
It also reports credential presence as booleans and whether a custom API endpoint
is configured. Credential values and the endpoint URL are omitted.

When temperature is omitted, its reported value is null, meaning the keyword will
be absent from the request. This report uses the same role resolution as the model
client. It describes current configuration; it does not reconstruct an earlier
run's settings, remaining persisted budget, or a caller's explicit model override.
Credential presence does not establish provider authentication, account access or
model compatibility, and other provider environment credentials are not inspected.

The command makes no provider, browser, search or database calls, creates no run
and changes no settings. Invalid configuration reports only field names, without
printing rejected values.

### JSON-mode request contract

Every `LLMClient.complete_json` request appends a trusted system instruction to
return one valid JSON object without Markdown fences or commentary. Original
role instructions and the user/data message are preserved. This prevents a
request from depending on an incidental JSON mention in untrusted page content.
The [OpenAI JSON-mode documentation](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode)
requires an explicit JSON instruction and documents rejection when the context
does not contain the required JSON marker. Semantic and source-assessment
prompts previously relied on their object examples alone.

The instruction is included before the UTF-8 request reservation is computed,
so each retry reserves its full request size. Existing persisted reservations
are retained. Strict object parsing, non-finite-number rejection, token-limit
selection and temperature settings remain unchanged. HTTP 400 diagnostics for
`parameter=messages` now point to message structure and JSON instructions.
# Saved requirement proposals

`verboisy run --resume RUN_ID` continues the saved requirements. If a proposal is
pending, it records a decline and continues the original contract.
`verboisy run --okresume RUN_ID` accepts the exact saved proposal and then resumes.
The two flags are mutually exclusive. Either flag can omit the ID to select the
latest incomplete run. Without a pending proposal, `--okresume` fails before
research and asks for `--resume`.

Inspect the complete pending proposal without model calls or database writes:

```bash
verboisy changes --run-id RUN_ID
```

A caller can offer a proposal using
`verboisy changes --run-id RUN_ID --proposal change.json`. The JSON file contains
`description`, `goal`, `schema` (a complete JSON Schema), and `task` (a complete
TaskSpec). These are replacement requirements, not partial updates. Preserve
existing task settings unless the offer explicitly changes them. The command
prints the exact proposal with `*` notices and both continuation commands, and
pauses the run before any research. It does not infer or generate a proposal.

Offering changes does not alter the active schema. Acceptance records the prior
requirements and decision in the existing event ledger, applies the replacements
atomically, and requeues browser work under the new requirements. Existing
snapshots and rejected candidates remain history. Old semantic and source
assessment caches are not reused under accepted requirements. New browser visits
may make model requests; this foundation does not yet replay saved snapshots.
Neither decision resets token/request accounting or raises the budget.

This initial workflow supports incomplete browser runs with zero accepted rows.
Completed runs, runs with accepted rows, and declared dataset ingestion changes
require a separate migration/revalidation workflow and are rejected. A proposal
whose baseline requirements have since changed is rejected as stale. No database
version migration is needed. The manual submission command does not itself detect feasibility conflicts.
The observed-range detector below uses this same decision boundary. Preferred
units and date presentation are available through the display options and apply
after evidence acceptance.


## Recovery inspection and setup

### Execution and recovery

`--max-steps N` limits page visits in the current invocation.

`--resume` resumes the latest incomplete run.

`--resume RUN_ID` resumes a specific persisted run.

`--headless` and `--headed` override browser visibility.

### Inspecting a saved run's status

Run `verboisy status --run-id <actual-run-id>` to inspect a run listed
by `verboisy runs`. The default database is the configured `SQLITE_DB_PATH`;
`--database` selects another existing ledger. Browser-only, dataset, paused,
failed and completed runs are supported.

The JSON report contains the saved goal, status and stop reason, accepted-record
and candidate counts, captures, snapshots, page outcomes, conflicts and journal
event counts. Accounting shows saved reported tokens, reserved request units and
distinct journaled search attempt reservations. These describe committed ledger
state, not provider billing or unjournaled historical requests. Coverage gap
event counts are historical; use `repairs` to verify current dataset gaps.

Status inspection uses a coherent SQLite read-only transaction and may run while
a writer holds the application lock. It does not resume the runner, validate
captured evidence, create a database, acquire a write lock, migrate a ledger or
make provider/browser/download calls. Raw event payloads and candidate records
are omitted. It does not infer a remaining budget from today's settings.

### Native configuration inspection

`verboisy native-config` inspects optional C++ quote-matcher selection and build
fingerprints without loading a binary. It uses shell environment flags, reports
missing or changed build inputs, and does not contact providers or open a ledger.
Matching hashes do not establish binary compatibility. See [native validation](native.md)
for the separate compiled-test gate.


### Command completion and validation

Console `verboisy`, `python -m verboisy`, and `python -m verboisy.cli.main` register
the same commands. Research/preparation returns 0 completed, 2 paused/incomplete,
1 failed/runtime error, and 130 interrupted. Read-only `stream-status` can succeed
while reporting an incomplete stored job.

JSON task/schema/projection/proposal readers reject duplicate keys, non-finite values
and unsafe Unicode within bounded regular-file reads. `maxrows` is an integer in
1..100000. Task identity uses scalar RFC 6901 pointers; root `id` is generated metadata
and source IDs require explicit projection. Optional absence is preserved.

`--proof` requires export. Publication I/O and contract/integrity errors have distinct
safe diagnostics; changing destination permissions cannot fix damaged saved evidence.
Provider inspection includes profile-specific response mode, token-limit and temperature
overrides. Display preferences are implemented; see [presentation](presentation.md).

---

[Overview](index.md) · [API](api.md) · [Licensing](licensing.md)
