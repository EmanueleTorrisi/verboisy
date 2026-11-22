<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

# Proof and provenance

`--proof` writes a human-readable report in addition to the structured export.

```bash
verboisy run \
  --goal "Find white laptops under €1000" \
  --schema '[name,brand,color,price,screen_size]' \
  --proof \
  --export laptops.csv
```

The report is written as `laptops.proof.txt`.

## Source of truth

Proof is rendered from SQLite state and accepted evidence. It does not ask a language model to invent a retrospective explanation.

The report includes:

- run ID, status, and goal;
- queued and visited page outcomes;
- accepted record evidence;
- source URLs and fetch times;
- field transforms and literal quotes;
- persisted run decisions;
- grouping and ordering notices;
- SmartID decisions when present.

The machine-readable evidence sidecar and checksummed manifest remain available beside each CSV or JSON export.

## What proof does not claim

A proof report demonstrates what the engine observed and how accepted values were supported. It does not independently establish that a public source is factually correct, nor does it claim exhaustive web coverage.


## Absence, grouping and reference provenance

An absent field has no fabricated leaf proof. Group keys retain presence/type tags;
an absent aggregate contributor has an explicit absence contribution. Unknown-only
numeric aggregates explain `no_observed_numeric_inputs` and yield null, never zero.
Raw, normalized and presented values remain distinct.

Ordinary generated IDs remain separate from source IDs. SmartID journals the reference
file/manifest hashes and mode; historical unbound events are labelled unrecorded when
the first binding is established. Verified streaming pages/exports replay saved source
and projection. Publication flushes files and syncs supported directory boundaries,
with the manifest last; this does not assert power-loss safety on all filesystems or
authenticity of the source.

## Workflow and analytical evidence

A reusable workflow adds its version, revision and exact file checksum to export
provenance. Declared HTML bindings link accepted fields to captured visible text or
table cells. Saved runs retain declared schema column order across replay.

Analytical streaming bundles include source and file checksums plus row evidence.
[Bundle verification](streaming.md#quality-updates-and-delivery) supports verification
on the receiving system, independently of the originating ledger.

---

[Overview](index.md) · [CLI](cli.md) · [API](api.md) · [Licensing](licensing.md)
