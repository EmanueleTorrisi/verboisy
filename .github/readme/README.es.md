<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# Investigación con evidencias y preparación de datos trazable

Verboisy combina investigación web verificada, preparación determinista de archivos y un flujo separado para grandes conjuntos locales. Esta es una versión de desarrollo; la cualificación del producto sigue pendiente.

Introducción localizada; los contratos técnicos completos en inglés se enlazan a continuación.

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## Instalación desde el repositorio

```bash
poetry install
poetry run verboisy --help
```

## Flujos disponibles

La investigación web verifica citas observadas antes de aceptar registros. Los archivos locales requieren directorios autorizados; los datos HTTP usan orígenes declarados. CSV, JSON, JSONL, TSV, texto, DOCX y XLSX tienen contratos acotados. Otros archivos pueden capturarse e indexarse sin interpretarlos.

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## Archivos locales grandes

stream utiliza un registro separado, búferes limitados, puntos de recuperación y acceso paginado. Se verificó un millón de filas JSONL de más de 1 GiB en Linux. Esto no constituye una garantía universal ni investigación web en streaming.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## Decisiones y semántica

--resume mantiene los requisitos y rechaza la propuesta; --okresume acepta solo los cambios ofrecidos. Los intervalos, unidades y fechas conservan las evidencias originales. Las series temporales requieren una política explícita: orden de instantes, ambigüedad de zona horaria y diagnóstico de huecos sin interpolación.

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## Estado y mantenimiento

El uso normal no requiere compilador C++. Las pruebas nativas son independientes. Actualmente no se aceptan contribuciones externas de código. La licencia sigue siendo BSD-2-Clause; las condiciones de distribución comercial deben revisarse antes de publicar.

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
