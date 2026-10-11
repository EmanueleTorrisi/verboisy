<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# Recherche mit Belegen, Datenaufbereitung mit Herkunftsnachweisen

Verboisy verbindet beleggestützte Webrecherche, deterministische Dateiaufbereitung und einen separaten Ablauf für große lokale Datensätze. Dies ist eine Entwicklungsversion; die Produktqualifizierung steht noch aus.

Lokalisierte Einführung; die vollständigen technischen Verträge auf Englisch sind unten verlinkt.

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## Installation aus dem Repository

```bash
poetry install
poetry run verboisy --help
```

## Verfügbare Abläufe

Webrecherche prüft beobachtete Zitate vor der Aufnahme von Datensätzen. Lokale Dateien benötigen freigegebene Verzeichnisse; HTTP-Daten verwenden deklarierte Ursprünge. CSV, JSON, JSONL, TSV, Text, DOCX und XLSX haben begrenzte Verarbeitungskontrakte. Andere Dateien können ohne Interpretation erfasst und indiziert werden.

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## Große lokale Dateien

stream verwendet eine separate Datenbank, begrenzte Puffer, Checkpoints und seitenweisen Zugriff. Eine Million JSONL-Zeilen mit mehr als 1 GiB wurden unter Linux überprüft. Das ist keine allgemeine Leistungsgarantie und kein Webrecherche-Streaming.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## Entscheidungen und Semantik

--resume behält Anforderungen bei und lehnt den Vorschlag ab; --okresume akzeptiert nur die angebotenen Änderungen. Bereiche, Einheiten und Datumsformate bewahren die Originalbelege. Zeitreihen benötigen eine explizite Richtlinie für chronologische Reihenfolge, Zeitzonenmehrdeutigkeit und Lückendiagnostik ohne Interpolation.

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## Status und Wartung

Für die normale Nutzung ist kein C++-Compiler erforderlich. Native Tests sind separat. Externe Codebeiträge werden derzeit nicht angenommen. Die aktuelle Lizenz bleibt BSD-2-Clause; kommerzielle Vertriebsbedingungen müssen vor Veröffentlichung geprüft werden.

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
