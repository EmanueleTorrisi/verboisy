<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# 根拠に基づく調査と、出所を追跡できるデータ整備

Verboisy は、検証済みのウェブ調査、決定的なファイル処理、大規模なローカルデータ用の独立した処理経路を提供します。現在は開発版であり、製品の適格性評価は未完了です。

日本語の導入説明です。完全な技術契約は、下記の英語文書を参照してください。

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## リポジトリからのインストール

```bash
poetry install
poetry run verboisy --help
```

## 利用できる処理経路

ウェブ調査では、観測した引用を検証してからレコードを受け入れます。ローカルファイルにはディレクトリの明示的な許可が必要です。HTTP データは宣言されたオリジンを使用します。CSV、JSON、JSONL、TSV、テキスト、DOCX、XLSX は限定された契約で処理します。その他のファイルは、内容を解釈せずに取得・索引化できます。

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## 大規模なローカルファイル

stream は別の台帳、上限付きバッファ、チェックポイント、ページ単位のアクセスを使用します。Linux で 1 GiB を超える 100 万行の JSONL を検証しました。これは普遍的な性能保証でも、ウェブ調査のストリーミングでもありません。

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## 判断とデータの意味

--resume は要件を維持して提案を拒否し、--okresume は提示された変更のみを承認します。範囲、単位、日付の表示を変えても元の根拠は保持します。時系列には、時点の順序、タイムゾーンの曖昧さ、補間を伴わない欠測診断のための明示的なポリシーが必要です。

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## 状態と保守

通常の利用に C++ コンパイラは不要です。ネイティブテストは別に実行します。外部からのコード貢献は現在受け付けていません。現在のライセンスは BSD-2-Clause のままです。商用配布の条件は公開前に審査する必要があります。

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
