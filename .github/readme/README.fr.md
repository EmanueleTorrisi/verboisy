<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# Recherche fondée sur des preuves, préparation traçable des données

Verboisy associe recherche web vérifiée, préparation déterministe de fichiers et traitement séparé de grands jeux de données locaux. Il s’agit d’une version de développement ; la qualification du produit reste à réaliser.

Introduction localisée ; les contrats techniques complets en anglais sont liés ci-dessous.

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## Installation depuis le dépôt

```bash
poetry install
poetry run verboisy --help
```

## Parcours disponibles

La recherche web vérifie les citations observées avant d’accepter les enregistrements. Les fichiers locaux exigent des répertoires autorisés ; les données HTTP utilisent des origines déclarées. CSV, JSON, JSONL, TSV, texte, DOCX et XLSX disposent de contrats limités. Les autres fichiers peuvent être capturés et indexés sans être interprétés.

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## Grands fichiers locaux

stream utilise un registre séparé, des tampons bornés, des points de reprise et un accès paginé. Un million de lignes JSONL dépassant 1 GiB ont été vérifiées sous Linux. Ce résultat n’est ni une garantie universelle ni un flux de recherche web.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## Décisions et sémantique

--resume conserve les exigences et refuse la proposition ; --okresume accepte uniquement les changements proposés. Intervalles, unités et dates conservent les preuves originales. Les séries temporelles exigent une politique explicite : ordre des instants, ambiguïtés de fuseau et diagnostic des lacunes sans interpolation.

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## État et maintenance

L’utilisation normale ne nécessite pas de compilateur C++. Les tests natifs sont séparés. Les contributions externes de code ne sont pas acceptées actuellement. La licence reste BSD-2-Clause ; les conditions de distribution commerciale doivent être examinées avant publication.

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
