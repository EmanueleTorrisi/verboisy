<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="220" /></p>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">Verboisy</h1>
<p align="center"><strong>연구 질문에서 출처를 확인할 수 있는 데이터셋까지.</strong></p>
<p align="center">근거 기반 조사 · 구조화 추출 · 로컬 데이터 · 이동 가능한 출처 기록</p>


## 제품 소개

Verboisy는 구조화된 정보와 그 정보의 출처를 확인하는 방법이 필요한 사용자를 위한 조사·데이터 추출 엔진입니다. 질문, 스키마, 허용된 출처로 작업을 정의합니다. 관찰 내용을 수집하고 제안된 레코드를 검증하며 근거와 출력 변환을 보존합니다. CLI와 Python API로 반복 가능한 작업과 저장된 작업의 재개가 가능합니다.

또한 모델·검색·브라우저 호출 없이 결정론적 어댑터로 로컬 파일 및 선언된 HTTP 데이터셋을 준비합니다. 대용량 로컬 입력에는 제한된 버퍼와 디스크 원장을 사용하는 별도 흐름이 있습니다.

**소스 열람 가능, 실행은 별도 라이선스 필요.** [LICENSE](../../LICENSE)는 소스 검토를 허용하며 실행은 허용하지 않습니다. 테스트, 수정, 배포에는 별도 서면 허가가 필요합니다. 아래 예시는 허가된 사용을 설명합니다.

## 이 접근 방식의 가치

JSON이나 표만으로는 사실을 직접 관찰했는지, 값이 어떻게 변환되었는지 알 수 없습니다. Verboisy는 이를 데이터 처리 과정에 포함합니다.

- **채택 전 근거 검증:** 모델 후보는 관찰된 출처 연결과 결정론적 검증을 필요로 하며 의미 검토는 별도 단계입니다.
- **사용자가 정하는 계약:** JSON Schema, 식별 규칙, 출처 범위, 비교 가능성이 허용할 출력을 정의합니다.
- **복구 가능한 작업:** 불변 캡처, 체크포인트, 요청 기록이 진행 상황과 사용량을 보존합니다.
- **설명 가능한 변환:** 단위, 투영, 표시 및 그룹화가 원본 값과 기여 레코드에 연결됩니다.
- **명시적인 결정:** 질문이나 스키마를 몰래 바꾸지 않고 변경안을 제시하여 작업을 일시 중지합니다.

분석, 참조 데이터 수집, 데이터 준비, 내부 정보 업무 및 재현 가능한 조사에 유용합니다. 과학 연구나 규제 대상 용도에서는 출처, 표본, 결론을 독립적으로 검토해야 합니다. 장기 목표는 신뢰할 수 있는 근거 기반 데이터 추출 표준이 되는 것이며, 이미 시장을 선도한다는 주장이 아닙니다.

## 작업 흐름과 형식

웹 조사는 브라우저와 설정된 모델을 사용하고 검색을 통한 출처 발견은 선택 사항입니다. 결정론적 준비는 허용된 파일이나 선언된 HTTP GET 출처를 읽습니다. 별도 스트리밍 흐름은 건수, 레코드 페이지 및 체크포인트를 제공합니다.

| 입력 | 해석 |
| --- | --- |
| CSV / TSV | 정확한 문자열, 명시적 헤더 및 행 너비 검사 |
| JSON / JSONL | 엄격하게 디코딩하는 타입 지정 객체 |
| 텍스트 | 원본 위치가 있는 텍스트 레코드 |
| DOCX / XLSX | 문서화된 제한이 있는 어댑터, 매크로·수식 실행 없음 |
| 이미지, 영상 및 기타 파일 | 불변 바이트 캡처, 해시와 참조, 자동 내용 해석 없음 |
| 시계열 | 명시적 계열·시각 규칙, 정렬 및 누락·중복 진단 |

바이너리 캡처는 OCR이나 모든 문서의 해석을 의미하지 않습니다. OAuth, 데이터베이스 드라이버, 애플리케이션 커넥터 및 API 페이지 처리는 별도 통합이 필요합니다. [형식](../../docs/formats.md)을 참조하세요.

## 설치와 설정

Python **3.11–3.14**, Poetry 및 실행에 대한 서면 허가가 필요합니다. CI는 Linux, macOS, Windows를 대상으로 합니다. 모델 조사에는 호환 프로필과 자격 증명이, 브라우저 수집에는 Chromium과 시스템 라이브러리가 필요합니다. 로컬 입력에는 명시적 디렉터리 허가와 충분한 디스크 공간이 필요합니다. 일반 설치에는 C++ 컴파일러가 필요하지 않습니다.

```bash
poetry install
poetry run verboisy --help
```

키는 [.env.example](../../.env.example)을 참고하여 개인 환경이나 `.env`에 보관하고 커밋하지 마세요. 셸 예시는 POSIX 문법이며 Windows에서는 동등한 방법으로 환경 변수를 설정해야 합니다.

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

`model-config`는 설정과 자격 증명의 존재 여부만 표시하고 키 값은 노출하지 않습니다. 결정론적 로컬 준비는 모델이나 브라우저가 필요 없습니다. [공급자](../../docs/providers.md)와 [검증](../../docs/validation.md)을 참조하세요.

## 웹 조사와 API

```bash
poetry run verboisy run \
  --goal "연구 기관과 명시적으로 공개된 공식 웹사이트를 찾아 주세요" \
  --schema '[이름,웹사이트,국가]' \
  --export 연구기관.json
```

자동 발견에는 검색 공급자가 필요하며 작업에서 시작 URL을 명시할 수도 있습니다. JSON Schema로 타입과 제약을 구체화합니다. 없는 정보는 `null`로 남을 수 있고 근거 없는 값은 거부됩니다. 채택된 결과가 웹 전체의 완전성을 보증하지는 않습니다.

```python
from verboisy import run

결과 = run(
    goal="연구 기관과 공개된 공식 웹사이트를 찾아 주세요",
    schema=["이름", "웹사이트", "국가"],
    export="연구기관.json",
)
print(결과.run_id, 결과.status, 결과.records)
```

비동기 앱은 `arun`을 사용합니다. 일반 API는 채택된 레코드를 메모리에 구성하며, 큰 로컬 입력에는 스트리밍 흐름을 사용해야 합니다.

## 로컬 및 내부 데이터

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy입력"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy입력/관측데이터.jsonl' \
  --schema 관측스키마.json \
  --export 관측데이터.json
```

디렉터리와 스키마 파일이 있어야 합니다. 모델 자격 증명은 파일 시스템 접근 권한을 주지 않습니다. 선언된 HTTP 출처는 제한된 다운로드, 리디렉션 정책, DNS 고정 및 출처별 비밀 값을 사용합니다. 출처의 위치와 모델 실행 위치는 독립적입니다. 원격 모델로 관찰 내용이 전송될 수 있으므로 기밀 자료를 처리하기 전에 전송, 로그, 네트워크 및 보관 정책을 확인하세요.

## 대용량 데이터셋

```bash
poetry run verboisy stream \
  --database 관측스트림.db \
  --dataset-file 'jsonl=/srv/verboisy입력/관측데이터.jsonl' \
  --schema 관측스키마.json \
  --export 관측데이터.jsonl
```

스트리밍 원장은 불변 원본 청크와 트랜잭션 진행 상황을 보존합니다. `stream-status`로 작업을 확인하고 `stream --resume 작업ID`로 저장된 작업을 재개합니다. `StreamLedger`는 페이지 단위 읽기를 제공합니다.

Linux/Python 3.12의 JSONL 측정에서는 **1,000,000행**, **1,105,888,890바이트**를 준비·출력했고 최대 RSS는 **89.15 MiB**, 경과 시간은 **130.81초**였습니다. 원본 삭제 후 복구와 출력 무결성도 검증했습니다. 이는 특정 작업의 측정이며 보편적인 속도나 메모리 보장은 아닙니다. [스트리밍](../../docs/streaming.md)과 [벤치마크](../../docs/benchmarks.md)를 참조하세요.

## 제안, 재개와 근거

```bash
poetry run verboisy changes --run-id 실행ID
poetry run verboisy status --run-id 실행ID
poetry run verboisy run --resume 실행ID
```

`--resume`은 기존 요구를 유지하고 제안을 거절합니다. `--okresume`은 저장된 변경만 승인합니다. 제안은 타입, 열 또는 검색 범위를 바꿀 수 있습니다. 재개는 사용량을 초기화하거나 출처 권한을 암묵적으로 확대하지 않습니다.

범위는 범위로 유지합니다. 하한을 정확한 값이나 만들어 낸 상한으로 바꾸지 않습니다. 숫자형 min/max 열에는 적절한 스키마가 필요합니다. 기본 표시는 킬로그램, 미터, 일/월/년이며 대안을 명시해도 원본 근거를 보존합니다. 시계열 진단은 누락된 관찰을 보간하거나 모호한 현지 시각을 추측하지 않습니다.

이동 가능한 출력은 근거, 관련 이벤트, 출력 출처 기록과 해당하는 캡처 자료를 포함합니다. 그룹은 기여 레코드를 식별합니다. 체크섬은 매니페스트와 바이트 일치 여부를 확인하며 사실성이나 독립적인 진본성을 증명하지 않습니다. [출처 기록](../../docs/proof.md)을 참조하세요.

## 아키텍처와 문서

Python은 오케스트레이션, 계약, 어댑터, CLI 및 SQLite 원장을 담당합니다. 선택적 C++17 구성 요소는 Python 참조 구현을 유지하며 특정 근거 비교를 가속합니다. 테스트와 CI는 플랫폼, 브라우저, 복구 및 무결성을 검증하고 문장·분기의 완전한 커버리지를 요구합니다. 실제 조사 품질과 공급자 호환성은 별도 평가가 필요합니다.

[CLI](../../docs/cli.md) · [API](../../docs/api.md) · [계약](../../docs/contracts.md) · [식별](../../docs/smartid.md) · [수집](../../docs/ingestion.md) · [표시](../../docs/presentation.md) · [의미](../../docs/research-semantics.md) · [설계](../../ARCHITECTURE.md) · [변경 기록](../../CHANGELOG.md)

## 라이선스, 데모와 상업 문의

Verboisy는 독점 소프트웨어로 **오픈소스가 아닙니다**. 영문 LICENSE가 공식 조건이며 이 번역은 권리를 변경하지 않습니다. 식별자는 `LicenseRef-Verboisy-Source-Inspection-1.0`입니다. 제삼자 구성 요소는 각자의 라이선스를 유지합니다. 실행, 테스트, 수정, 통합, 배포 및 호스팅에는 별도 서면 허가가 필요합니다.

데모, 평가, 사내·기업 라이선스, 투자, 제휴 및 향후 유급 협업은 **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** 으로 문의하세요. 작업 흐름, 출처, 규모, 환경을 설명하고 자격 증명이나 기밀 자료는 보내지 마세요. 가격, 지원 및 권리는 개별 합의합니다. [라이선스](../../docs/licensing.md)와 [상업 문의](../../docs/commercial.md)를 참조하세요.

## 피드백과 협업

**Emanuele Torrisi**가 Verboisy를 만들고 유지하며 현재 유일한 개발자입니다. [버그 보고와 기능 요청](https://github.com/EmanueleTorrisi/verboisy/issues)을 환영합니다. 취약점은 [보안 정책](../SECURITY.md)에 따라 비공개로 보고하세요.

요청하지 않은 코드 기여는 받지 않습니다. 유료 협업은 범위, 보수, 기밀 유지와 지식재산권에 대한 사전 합의가 필요합니다. 버전 변경은 [변경 기록](../../CHANGELOG.md), 0.1.0에서 1.0.0까지의 발전은 [버전 역사](../../docs/development-roadmap.md)에 기록합니다. [참여 정책](../CONTRIBUTING.md)과 [저작권](../../COPYRIGHT.md)을 확인하세요.
## 실제 워크플로 예제

[연구 기관 목록](../../examples/research_catalog/README.md) ·
[대규모 로컬 관측 데이터 처리](../../examples/streaming_observations/README.md) ·
[버전 이력: 0.1.0–1.0.0](../../docs/development-roadmap.md)
