<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# 基于证据的研究与可追溯的数据准备

Verboisy 提供经过验证的网页研究、确定性文件处理，以及独立的大规模本地数据处理流程。目前为开发版本，产品资格验证尚未完成。

这是本地化入门说明；完整技术契约请参阅下方链接的英文文档。

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## 从仓库安装

```bash
poetry install
poetry run verboisy --help
```

## 可用流程

网页研究在接受记录前验证已观察到的引用。本地文件需要明确授权的目录，HTTP 数据使用声明的来源。CSV、JSON、JSONL、TSV、文本、DOCX 和 XLSX 按限定的契约处理。其他文件可以被采集和索引，但不会因此被解释。

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## 大型本地文件

stream 使用独立账本、有界缓冲区、检查点和分页访问。已在 Linux 上验证超过 1 GiB 的一百万行 JSONL。该结果并非通用性能保证，也不代表支持网页研究流式处理。

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## 决策与数据语义

--resume 保留原要求并拒绝提议；--okresume 仅接受明确提出的变更。范围、单位和日期的显示不会覆盖原始证据。时间序列需要明确策略，以按实际时刻排序、处理时区歧义，并在不插值的情况下诊断缺口。

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## 状态与维护

正常使用不需要 C++ 编译器。原生测试单独执行。目前不接受外部代码贡献。当前许可证仍为 BSD-2-Clause，商业分发条款需要在公开发布前审核。

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
