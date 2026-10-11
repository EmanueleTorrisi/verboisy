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
