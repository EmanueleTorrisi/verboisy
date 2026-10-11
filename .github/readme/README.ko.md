<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="240" /></p>

# 근거에 기반한 조사와 출처를 추적할 수 있는 데이터 준비

Verboisy는 검증된 웹 조사, 결정적 파일 처리, 대규모 로컬 데이터용 별도 처리 경로를 제공합니다. 현재 개발 버전이며 제품 적격성 검증은 아직 완료되지 않았습니다.

한국어 소개이며, 전체 기술 계약은 아래의 영어 문서를 참조하십시오.

[English](../../README.md) · [Italiano](README.it.md) · [Deutsch](README.de.md) ·
[Français](README.fr.md) · [Español](README.es.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · [简体中文](README.zh-CN.md)

## 저장소에서 설치

```bash
poetry install
poetry run verboisy --help
```

## 지원하는 작업 흐름

웹 조사는 관측한 인용문을 검증한 뒤 레코드를 수락합니다. 로컬 파일은 명시적으로 허용된 디렉터리가 필요하며 HTTP 데이터는 선언된 출처를 사용합니다. CSV, JSON, JSONL, TSV, 텍스트, DOCX, XLSX는 제한된 계약에 따라 처리합니다. 다른 파일은 해석하지 않고 수집하여 색인할 수 있습니다.

```bash
poetry run verboisy run \
  --goal "Find research institutions and their published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

[Providers](../../docs/providers.md) · [Sources](../../docs/ingestion.md) ·
[File capabilities](../../docs/formats.md)

## 대규모 로컬 파일

stream은 별도 원장, 제한된 버퍼, 체크포인트, 페이지 단위 접근을 사용합니다. Linux에서 1 GiB를 넘는 JSONL 백만 행을 검증했습니다. 이는 모든 환경의 성능을 보장하거나 웹 조사 스트리밍을 제공한다는 뜻이 아닙니다.

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --export observations.jsonl
```

[Streaming contract](../../docs/streaming.md)

## 결정과 데이터 의미

--resume은 기존 요구 사항을 유지하고 제안을 거절합니다. --okresume은 제시된 변경만 수락합니다. 범위, 단위, 날짜를 표시할 때도 원래 근거를 유지합니다. 시계열에는 시점 정렬, 시간대 모호성 처리, 보간 없는 누락 진단을 위한 명시적인 정책이 필요합니다.

[Semantics](../../docs/research-semantics.md) · [Display](../../docs/presentation.md) ·
[CLI](../../docs/cli.md)

## 상태와 유지 관리

일반 사용에는 C++ 컴파일러가 필요하지 않습니다. 네이티브 테스트는 별도로 실행합니다. 현재 외부 코드 기여는 받지 않습니다. 현재 라이선스는 BSD-2-Clause이며 상업적 배포 조건은 공개 전에 검토해야 합니다.

```bash
make validate
make repo-check
```

[Architecture](../../ARCHITECTURE.md) · [Release gates](../../docs/release-checklist.md) ·
[Security](../SECURITY.md) · [Maintainer policy](../CONTRIBUTING.md) ·
[Licence](../../LICENSE) · [Commercial review](../../docs/distribution.md)
