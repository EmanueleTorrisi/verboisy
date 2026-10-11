<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# Ricerca con prove, preparazione con provenienza

Verboisy combina ricerca web verificata, preparazione deterministica di file e un percorso separato per grandi dataset locali. Questa è una versione di sviluppo: la qualificazione del prodotto è ancora in corso.

Introduzione localizzata; i contratti tecnici completi in inglese sono collegati sotto.

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## Installazione dal repository

```bash
poetry install
poetry run verboisy --help
```

## Flussi disponibili

La ricerca web verifica citazioni osservate prima di accettare i record. I file locali richiedono directory autorizzate; i dati HTTP usano origini dichiarate. CSV, JSON, JSONL, TSV, testo, DOCX e XLSX hanno contratti limitati; gli altri file possono essere acquisiti e indicizzati senza interpretazione.

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## Grandi file locali

Il comando stream usa un registro separato, buffer limitati, checkpoint e pagine di record. Un milione di righe JSONL, oltre 1 GiB, è stato verificato su Linux. Non è una garanzia universale né un flusso di ricerca web.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## Decisioni e semantica

--resume mantiene i requisiti e rifiuta la proposta; --okresume accetta solo le modifiche offerte. Intervalli, unità e date conservano le prove originali. Le serie temporali richiedono una politica esplicita: ordinamento degli istanti, gestione delle ambiguità di fuso e diagnostica delle lacune senza interpolazione.

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## Stato e manutenzione

Nessun compilatore C++ è richiesto per l’uso normale. I test nativi sono separati. I contributi esterni di codice non sono attualmente accettati. La licenza attuale resta BSD-2-Clause; la decisione sulla distribuzione commerciale richiede revisione prima della pubblicazione.

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
