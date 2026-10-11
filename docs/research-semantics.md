<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Research semantics and useful outcomes

Research requirements, accepted observations and display choices are separate
contracts. A useful explanation must identify which of these it concerns. No
absence in saved rows proves that a fact is unavailable everywhere.

| Requirement | Product behavior | Boundary |
| --- | --- | --- |
| Observed complete range | Preserve both endpoints and the stated unit; offer a compatible schema when a numeric column conflicts | A lower bound is not an exact number or a complete range; no invented endpoints or sex attribution |
| Units | Default kg/metres; explicit lb/ft/source preferences are available | Conversion needs observed unit context; original evidence remains unchanged |
| Dates | Default day/month/year; explicit mdy/iso/source preferences are available | Ambiguous source dates are not reinterpreted through display preferences |
| Goal or column alternative | Ground every affected field and goal change, save the exact offer, pause before export | No automatic removal, added column or new search scope |
| Ordinary resume | Continue the existing contract and decline the pending alternative | A declined equivalent offer is not repeatedly presented |
| Accepting resume | `--okresume` accepts the saved proposal against its exact baseline | No unrelated permissions, budget enlargement or hidden source changes |
| Null columns | Explain entirely null columns among accepted observations | No universal impossibility claim; null, zero, false and empty text remain distinct |
| Time series | Explicit chronological ordering and accepted-observation diagnostics | No cadence inferred from a field name or from the research goal |

See [Display preferences](presentation.md) and [CLI](cli.md) for unit/date options
and saved change inspection. Numeric min/max columns remain a separate requested
schema; an interval-string proposal does not silently split columns. Suggestions
may change the goal, add/remove columns or change types only through the same
checked, explicit decision boundary. Protected identity, field and time-series
requirements cannot be removed by an automatic alternative.

## Explicit time-series tasks

Supply `time_series` in the ordinary task JSON accepted by both CLI and Python:

```json
{
  "dataset_sources": [
    {"url": "file:///srv/verboisy-inputs/observations.jsonl", "format": "jsonl"}
  ],
  "time_series": {
    "timestamp_field": "observed_at",
    "timestamp_kind": "date-time",
    "series_fields": ["station"],
    "assume_timezone": null,
    "interval_seconds": 3600
  }
}
```

Grant local directories separately through `DATASET_LOCAL_ROOTS`. The same policy
can accompany web research with explicit browser seeds. Time-series policy does
not grant sources, define a model provider or add paid requests.

Timestamp and series fields must be top-level output columns. Existing explicit
identity fields must include the timestamp and every series field; a station-only
identity would merge different observations and is rejected. Without explicit
identity fields, ordinary exact-record identity still applies. Repeated identical
source records may therefore already be deduplicated before the accepted-record
report. Use the scaled physical-row workflow when preserving every source row is
required; it does not implement this materialized ordering operation.

Groups appear in first-observed order. Within a group, observations are ordered by
actual UTC instant, with stable ordering for equal instants. Printed timestamps
and offsets remain unchanged. Invalid timestamps or series keys remain visible at
the end, with bounded diagnostic examples. Grouping and explicit `order` conflict
with this automatic ordering and fail before acquisition. User requirements and
saved task policy stay fixed across resume.

## Timezones and cadence

Date-time input requires `YYYY-MM-DDTHH:MM:SS`, optional microseconds, and an explicit
`Z` or numeric offset. Naive date-times require a declared `assume_timezone`, such
as `Europe/Rome`. Its timezone database must be available locally. A repeated or
nonexistent daylight-saving clock reading is rejected as ambiguous; the program
never chooses a fold on the user's behalf. An explicit offset resolves an instant
without that ambiguity. Leap seconds and guessed locale formats are not accepted.

For calendar dates, choose `timestamp_kind: "date"`. Dates require `YYYY-MM-DD`,
allow no timezone assumption, and use whole-day cadence. Date-times use fixed
elapsed seconds. A daily local wall-clock schedule across daylight saving is not
a fixed 86,400-second schedule; calendar/market/business-day schedules need their
own future contract. Cadence is optional and never inferred.

## Diagnostics and completeness

The manifest's `time_series` report counts invalid timestamps, invalid series keys,
duplicate instants, missing observations between on-grid consecutive observations,
and off-grid intervals. Gap counts use integer arithmetic without allocating
missing rows, even when the interval is very large. Duplicate observations remain
visible if they survived ordinary admission. No interpolation, averaging,
resampling or endpoint padding is applied.

The report is scoped to `accepted_records`. It does not change the underlying
research completion decision, establish endpoint coverage, or certify that every
real-world observation has been found. `COMPLETED` concerns the existing research
contract, not an independently qualified continuous series. Inspect diagnostics
before using an export for analysis. Entirely null field notices and counts have
the same accepted-record scope.

Ordering happens before public IDs and output-to-evidence mappings are assigned,
and before display formatting. Consequently, changing displayed units or date
format on completed resume cannot alter chronology or original evidence. Reports,
notices, the task contract and contributor mappings travel with the ordinary
portable manifest. Checksums provide integrity relative to that manifest, not
independent authentication or factual truth.

## Verification scope

Offline fixtures cover offset chronology, DST ambiguity, leap dates, duplicate and
large-gap handling, null coverage, immutable evidence on re-export, fixed task
policy and historical declined proposals. Existing range, unit/date presentation
and proposal-decision suites are run alongside them. This is engineering evidence;
cross-domain human-reviewed held-out research and live provider qualification
are assessed through [research evaluation](evaluation.md). Evaluation
requires authorized sources and an explicit provider spending limit.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
