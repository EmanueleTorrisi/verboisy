<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Engineering history

This file retains the engineering sequence completed before the finite release gates.
The active plan is [Production acceptance](production-acceptance.md). Historical
next-step language does not create additional release requirements.

The maintainer reports that Verboisy has remained private. The repository currently
contains BSD-2-Clause notices. Keep the licensing decision pending while ownership,
prior distribution and third-party terms are reviewed; do not silently change notices.
The maintainer currently intends to remain the sole code contributor. Any contribution
policy should reflect that choice when publishing, rather than inviting code submissions.

1. Grounded numeric-unit presentation now replays accepted source bindings and dataset
   projections, preserving raw evidence and recording target units in cell lineage.
2. Shared presentation configuration now supports environment defaults, saved-run
   precedence, explicit overrides and a dedicated supported-format reference.
3. Output preparation/publication now has its own module, preserving API compatibility,
   saved-run behavior and evidence mappings. Continue splitting research and ingestion
   orchestration only along clear responsibilities; see [Architecture](architecture.md).
   Accepted-row comparability and deterministic gap/repair planning now live in
   `core/dataset_consistency.py`, behind the existing runner methods.
   Source windowing and ranking now live in `core/source_batches.py`, with the
   current plan and accepted-count callbacks supplied by the runner.
   Grounded unit-normalization journaling now has a dedicated workflow in
   `core/unit_normalization.py`; arithmetic and replay remain in `core/units.py`.
   Exhausted-frontier diagnostics and outcome precedence now live in
   `core/run_outcome.py`, preserving diagnostic writes before pause decisions.
   Snapshot capture and candidate admission now enforce page/snapshot run ownership
   before writes, preventing cross-run evidence attachment without a schema migration.
   Admission now also rejects supplied snapshot contents that differ from saved
   evidence, while retaining compatibility with historical optional defaults.
   Snapshot capture now has real-SQL duplicate and insertion-fault tests, including
   unchanged admitted proofs, rollback across reopening and successful retry.
   Snapshot loading now rejects invalid owned payloads and mismatched internal IDs
   with controlled errors, preserving read-only and historical-default compatibility.
   Accepted-candidate lookups now check candidate run ownership before returning
   comparison evidence, with read-only real-ledger coverage of damaged references.
   Both lookups also share accepted-disposition and payload validation, rejecting
   damaged selections while retaining historical optional metadata defaults.
   Selected candidate payloads must also retain the requested identity, including
   compound fields; same-identity replacement and stable row IDs remain unchanged.
   Accepted comparison candidates also require an existing snapshot in their run,
   rejecting foreign, missing and null bindings through the existing lookup queries.
   Lookup now distinguishes absent selections from orphaned selected candidate
   references, reporting the latter as controlled errors instead of returning None.
   Portable evidence assembly now shares reference ownership and disposition checks,
   rejecting incomplete proof chains before replacing existing export generations.
   Portable payloads also receive structural validation and snapshot-ID checks,
   retaining the original historical evidence shape instead of dumping model defaults.
   Portable evidence now verifies admission identity keys against saved task rules,
   including compound fields and the existing whole-record fallback.
   Shared saved-evidence validation now lives in `storage/saved_evidence.py`,
   while SQL selection, task loading and transaction ownership remain in the ledger.
   Ledger close now attempts application writer-lock release even when connection
   cleanup fails, with real-lock coverage of writer, reader and initialization paths.
   Connection cleanup also covers row-factory setup in both constructor modes,
   including runtime, SQLite and interruption faults before ledger queries begin.
   Normalized record views now live in `storage/record_view.py`, with pointer
   replacement and unit replay separated from ledger reads and integrity checks.
   Frontier ranking now lives in `storage/frontier_selection.py`; the ledger
   retains run-scoped queries, depth filtering and transactional page activation.
   Candidate admission now lives in `storage/admission.py`, preserving the complete
   snapshot, disposition, conflict and replacement transaction behind the store API.
   Snapshot persistence now lives in `storage/snapshots.py`, preserving run ownership,
   immutable capture and validated replay behind the existing ledger methods.
   Schema initialization and supported upgrades now live in `storage/ledger_schema.py`,
   retaining the existing version contract and constructor cleanup boundary.
   Writable initialization now rejects ambiguous version metadata before schema
   or upgrade statements, with persisted-state and writer-lease regressions.
   Admission now validates previous selected references before disposition writes,
   preventing damaged references from changing another run's candidate history.
   Admission also reuses payload-chain validation and checks selected raw values,
   covering compound identities, whole-record keys and historical JSON compatibility.
   Raw-value integrity is now shared by admission, record views and exports,
   with cross-path coverage preserving read-only state and prior export generations.
   Comparison lookups now share snapshot and raw-value validation too, preserving
   historical JSON and controlled identity errors before returning accepted evidence.
   Saved journal decoding now rejects ambiguous and non-finite JSON. Dataset export
   preflights journal reads and reservation accounting before disturbing old files,
   and reuses captured decisions throughout each portable generation.
   Dataset asset replay now shares acquisition endpoint checks across SQLite and
   portable bundles; repeat capture also validates the existing acquisition owner.
   Writable schema creation, supported upgrades and stable-ID backfill now commit
   together, with DDL denial, interruption, version-write failure and retry coverage.
   Admission compares validated canonical values, so historical JSON presentation
   cannot create false identity conflicts; genuine changes retain preference rules.
   Initial discovery replay now validates saved acquisition structure, URLs and
   domain policy before task/frontier publication, preserving paid-request reuse.
   Per-query replay caches now reject malformed or conflicting acquisitions and
   isolate inputs, writers and replay values while retaining empty-search retry.
   Candidate admission transactions now have SQL fault-injection coverage across
   insertion, conflict and replacement stages, including reopen and successful retry.
   Initial source selection and acquisition/frontier publication now live together
   in `core/initial_discovery.py`, behind the existing API wrappers and hooks.
   Initial query journaling now retains completed permitted results across later
   query budget/cancellation failures, avoiding repeated provider work on resume.
   Initial discovery now saves successful acquisition results before task/frontier
   publication, allowing interrupted publication to resume without repeating search.
   Dataset ingestion now checkpoints initial-read and unexpected execution failures
   accurately, and preserves interruption status for keyboard interrupts.
   Browser cleanup now attempts remaining resources after cancellation and then
   propagates the first cancellation, retaining cleanup order and repeat-close behavior.
   Run finalization now attempts ledger recovery and accounting checkpoints even
   when browser cleanup fails or is cancelled, preserving resumable work.
   Page evidence preparation and semantic-plan gating now live in
   `core/page_batches.py`, preserving runner hooks and coverage-gap publication order.
   Source-yield replay, scoring and journaling now live in `core/source_productivity.py`.
   Cached totals publish after durable events, preventing double-counting on failed-write retries.
   Bounded pagination control checks now live in `core/page_pagination.py`, preserving
   deferred configuration reads and interaction increments after successful clicks.
   Reviewed-candidate comparison and admission journaling now live in
   `core/candidate_admission.py`, retaining ledger write order and runner target checks.
   Proposal journaling, candidate review and grounded change-offer gating now live
   in `core/proposal_review.py`, preserving the current-contract priority and pause order.
   Rendered observation capture now lives in `core/page_capture.py`, retaining scope
   and size guards before evidence creation and the existing capture script import.
   Semantic-plan journaling now lives in `core/semantic_plan_journal.py`, preserving
   durable publication order and deferred access to model request context.
   Scoped page-link selection, fallback deferral and frontier journaling now live
   in `core/frontier_discovery.py`, behind the existing runner methods.
   Accepted dataset binding replay and interrupted row journal recovery now live
   in `extractor/dataset_journal.py`, retaining read-only inspection and write ordering.
   Deterministic dataset row snapshots and proofs now live in
   `extractor/dataset_evidence.py`, preserving the ingestion import path and resume bindings.
   Projected dataset replacement comparison now lives in `core/dataset_comparison.py`,
   preserving grounded metadata and the existing ingestion verification hook.
   Assessment cache replay and source-fitness journaling now live in
   `core/assessment_journal.py`, with deferred model access and existing failure ordering.
   Targeted repair search and durable retry journaling now live in
   `core/repair_discovery.py`; the runner retains invocation state and its scope/provider hooks.
   Candidate fitness comparison and evidence-preserving metadata refresh checks
   now live in `core/evidence_comparison.py`, behind the runner's existing methods.
4. Add concise module/API docstrings and comments explaining invariants, failure
   recovery and non-obvious decisions. Avoid comments that merely repeat statements.
5. Offline benchmarks now cover dataset parsing, evidence verification, grouping,
   sorting and portable lineage. Collect CPU, wall-time and Python-allocation baselines
   on the target machine; see [Benchmarks](benchmarks.md). Synthetic fixtures establish
   repeatability, while production input profiles still need separate assessment.
6. Verification now reuses bounded private compiled models; measure its improvement
   against the baseline before selecting a bounded C/C++ implementation. Grouped
   lineage now reuses ledger inputs and replay results within each generation;
   benchmark both scalar and grouped chains against their retained digests. Preserve a
   Python reference implementation, test identical semantics, measure call overhead,
   and validate portable builds before making the native path a default. The first
   optional C++ experiment now implements literal quote boundaries using CPython
   Unicode semantics; see [Native matching](native.md). Python remains the default.
   Bounded native batches now retain complete verification rejection results.
   Dedicated Linux/macOS CI jobs build both extensions and require native tests
   without skips; collect those results before automatic selection or native
   release packaging. Local tests alone do not establish matrix portability.
7. Finalise source-available/commercial licensing and a sole-maintainer contribution
   policy after legal review, then prepare commercial packaging and onboarding.

The optional native matcher is a source-build experiment. Portable native release
wheels and commercial rights clearance remain pending.

Saved snapshot replay also verifies that the originating page still exists in
that run. Admission, selected-record comparisons and exports share this check;
a missing or foreign page stops the operation before evidence is used or written.
Historical page status and redirect URLs do not alter ownership, and valid
snapshot payloads retain their original representation.

Requirement-change replay validates the full proposal and decision sequence.
A decision must close the pending proposal with its original baseline and saved
previous requirements; malformed, duplicate or orphan decisions stop inspection,
resume and planning-cache replay before changes are applied. JSON decoding also
rejects duplicate keys and non-finite numbers. These consistency checks preserve
history and consumed budgets; they do not authenticate an externally edited ledger.

Saved snapshots, accepted candidates, selected raw records and journal events
share strict JSON decoding before model validation. Repeated keys at any depth,
including escaped equivalents, and non-finite or overflowing numbers stop replay,
comparison, admission and export. Valid historical JSON retains its field order,
values and optional-field omissions; this boundary never repairs saved evidence.

Saved range offers preflight their existing newest-first window of at most 100
rejected candidates before publishing a proposal. Strict candidate decoding and
owned snapshot replay run before resume journals presentation changes or starts
research. The same decoded models feed the offer, avoiding a second scan. Missing
snapshots remain skipped; evidence outside the bounded window is not inspected.

Batch snapshot reuse is scoped to one saved-range scan or evidence decode. Each
range snapshot reference is loaded once, including unavailable references;
evidence batches validate each distinct reference and exact JSON payload once.
Every candidate, ownership link and selected raw record is still checked.
Independent deep copies preserve returned model and dictionary isolation. A new
operation reads the ledger again, including changes made after an earlier failure.

Portable asset manifests and checksummed sidecars use the same strict JSON
decoder as saved ledger evidence. Duplicate keys at any depth, escaped duplicate
keys and non-finite or overflowing numbers fail before capture replay. The
sidecar checksum is checked before its JSON is decoded; a matching checksum
proves byte consistency, not that the JSON is unambiguous or factually true.
Valid historical bundles, including supported JSON byte encodings, still replay
without changing their bytes, identifiers or source row values.

Assessment cache publication passes an independent payload to the journal writer
and publishes the invocation entry only after that write succeeds. A writer's
retained or mutated arguments cannot alter subsequent response replay. Cache
selection ignores events explicitly labelled with another kind, while preserving
legacy entries that omit the kind and the existing corrupt-entry skip policy.
These boundaries do not alter grounding, candidate acceptance or provider budgets.

Saved run loading checks schema and task JSON for duplicate keys, non-finite
numbers and object roots before downstream decisions, runner construction or
export publication. It preserves the original text and leaves schema semantics
and task model validation to their existing consumers. Run inventory retains its
read-only diagnostic contract, marking ambiguous task JSON as `invalid_task`.
These checks do not rewrite requirements, evidence, budgets or historical runs.

Resume preflights saved product options and inherited export destinations before
applying a pending requirement decision. Known options use strict booleans, text,
sort keys and source-policy fields; missing legacy options retain their defaults.
Saved output JSON must contain a path string, a list of path strings or null,
and existing destination collision checks still apply. Explicit output overrides
replace inherited paths. Invalid saved options stop before decisions, presentation
journaling or research; they do not reset budgets or rewrite the saved payload.

Resume resolves and validates its latest saved display entry before applying a
pending requirement decision. Explicit overrides cannot conceal malformed saved
units or date formats, and a null saved entry is distinct from no display history.
Valid partial historical entries retain field-specific environment backfill and
explicit override precedence. This preflight is read-only and does not publish
presentation events until the existing range-evidence checks have also passed.

The bounded rejected-candidate scan now precedes pending requirement decisions.
Owned snapshots and candidate JSON must validate before acceptance can rewrite
requirements or revisit the frontier, and before decline can close a proposal.
The same isolated models feed later range offers under the resulting contract;
there is no second scan. Existing newest-first limits and unavailable-snapshot
skipping remain unchanged. Failed scans leave decisions and budgets intact.

When no proposal remains pending, requirement-history replay also checks the
current goal, schema and task against the last closed decision. Acceptance must
leave the proposed contract; decline must leave the saved previous contract.
Task defaults are normalized for comparison, while seed URLs remain exempt
because initial discovery publishes them independently. A mismatch stops
inspection, proposal publication, planning-cache selection and resume without
rewriting history or resetting budgets. Pending proposals retain existing stale
baseline checks. This establishes ledger consistency, not external authenticity.

Resume preflights unpublished initial discovery before committing a requirement
proposal decision. A saved acquisition takes precedence; otherwise the saved
query journal is checked for malformed or conflicting entries. Completed
frontiers retain their existing replay boundary. This read-only check creates no
provider client, writes no events and restores any enclosing query context.
Discovery uses the already validated source policy, including legacy defaults,
rather than rereading raw product options. Publication retains its existing
validation and durable checkpoints; no provider retry or budget is reset.
