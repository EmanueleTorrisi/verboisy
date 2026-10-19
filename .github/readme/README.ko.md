<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="https://raw.githubusercontent.com/EmanueleTorrisi/verboisy/main/logo.png" alt="Verboisy" width="220" /></p>

<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/README.md">English</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.it.md">Italiano</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.de.md">Deutsch</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.fr.md">Français</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.es.md">Español</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ja.md">日本語</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.ko.md">한국어</a> ·
  <a href="https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/readme/README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">Verboisy</h1>
<p align="center"><strong>연구 질문에서 출처를 확인할 수 있는 데이터셋까지.</strong></p>
<p align="center">근거 기반 조사 · 구조화 추출 · 로컬 데이터 · 이동 가능한 출처 기록</p>


> **릴리스 상태:** 버전 `1.0.0`은 문서화된 워크플로, 지원 환경 및 검증된 한도 내에서 프로덕션 사용이 가능합니다. [릴리스 매트릭스](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json)는 이를 뒷받침하는 기술 검증, 실제 작업 평가, 독립 베타 테스트 및 릴리스 책임자의 승인을 기록합니다.

## 제품 소개

Verboisy는 구조화된 정보와 그 정보의 출처를 확인하는 방법이 필요한 사용자를 위한 조사·데이터 추출 엔진입니다. 질문, 스키마, 허용된 출처로 작업을 정의합니다. 관찰 내용을 수집하고 제안된 레코드를 검증하며 근거와 출력 변환을 보존합니다. CLI와 Python API로 반복 가능한 작업과 저장된 작업의 재개가 가능합니다.

또한 모델·검색·브라우저 호출 없이 결정론적 어댑터로 로컬 파일 및 선언된 HTTP 데이터셋을 준비합니다. 대용량 로컬 입력에는 제한된 버퍼와 디스크 원장을 사용하는 별도 흐름이 있습니다.

**소스 열람 가능, 실행은 별도 라이선스 필요.** [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE)는 소스 검토를 허용하며 실행은 허용하지 않습니다. 테스트, 수정, 배포에는 별도 서면 허가가 필요합니다. 아래 예시는 허가된 사용을 설명합니다.

## CLI 실행 예시

<p align="center">
  <a href="https://asciinema.org/a/kao32h7xRRkFwtkc">
    <img src="../assets/verboisy-demo.gif" alt="Verboisy CLI Demo">
  </a>
</p>

## 이 접근 방식의 가치

JSON이나 표만으로는 사실을 직접 관찰했는지, 값이 어떻게 변환되었는지 알 수 없습니다. Verboisy는 이를 데이터 처리 과정에 포함합니다.

- **채택 전 근거 검증:** 모델 후보는 관찰된 출처 연결과 결정론적 검증을 필요로 하며 의미 검토는 별도 단계입니다.
- **사용자가 정하는 계약:** JSON Schema, 식별 규칙, 출처 범위, 비교 가능성이 허용할 출력을 정의합니다.
- **복구 가능한 작업:** 불변 캡처, 체크포인트, 요청 기록이 진행 상황과 사용량을 보존합니다.
- **설명 가능한 변환:** 단위, 투영, 표시 및 그룹화가 원본 값과 기여 레코드에 연결됩니다.
- **명시적인 결정:** 질문이나 스키마를 몰래 바꾸지 않고 변경안을 제시하여 작업을 일시 중지합니다.

분석, 참조 데이터 수집, 데이터 준비, 내부 정보 업무 및 재현 가능한 조사에 유용합니다. 과학 연구나 규제 대상 용도에서는 출처, 표본, 결론을 독립적으로 검토해야 합니다. 장기 목표는 신뢰할 수 있는 근거 기반 데이터 추출 표준이 되는 것이며, 이미 시장을 선도한다는 주장이 아닙니다.

### 해석이 가치를 더하는 작업에 AI 활용

Verboisy는 결정론적 코드와 의미 해석을 담당하는 AI를 결합합니다. 구조화된 파일 읽기, 스키마 검증, 관찰된 근거와의 대조 및 내보내기는 코드로 실행하고, 워크플로에 필요한 계획과 해석에 모델을 활용합니다. 결정론적 단계는 모델 토큰을 소비하지 않으므로 같은 작업을 유료 LLM에 맡길 때 발생하는 추론 요금을 피할 수 있습니다. 로컬 데이터셋 준비는 모델 제공업체 없이도 완결할 수 있습니다.

이 설계는 불필요한 모델 호출을 줄이고 지출을 확인하기 쉽게 합니다. 전체 비용 절감 폭은 작업, 모델, 재시도 및 검토 노력에 따라 달라집니다. 공정한 비교는 동일한 출처, 출력 요구 사항 및 품질 기준을 적용하고 실패한 시도까지 포함합니다. 근거 검증은 뒷받침되지 않는 출력을 줄이지만, 의미적 정확성을 위해서는 신뢰할 수 있는 출처와 내용 검토가 필요합니다.

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

바이너리 캡처는 OCR이나 모든 문서의 해석을 의미하지 않습니다. OAuth, 데이터베이스 드라이버, 애플리케이션 커넥터 및 API 페이지 처리는 별도 통합이 필요합니다. [형식](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/formats.md)을 참조하세요.

## 설치와 설정

Python **3.11–3.14**와 서면 실행 허가가 필요합니다. Poetry는 개발 도구이며 설치 후 명령은 `verboisy`입니다. 릴리스 매트릭스에 명시된 운영체제와 인터프리터 구성을 사용하세요. 웹 조사에는 공급자 설정, Chromium과 시스템 라이브러리가 필요합니다. 로컬 입력에는 디렉터리 허가와 디스크 공간이 필요하며 C++ 컴파일러는 필요하지 않습니다.

허가된 체크아웃에서 다음 명령을 실행하세요. pipx가 설치되어 있으면 `pipx install .`로 프로젝트 밖에서도 명령을 사용할 수 있습니다. 허가된 PyPI 공개 후에는 `pipx install verboisy`를 사용할 수 있습니다. 현재 PyPI에 공개되어 있다고 가정하지 않습니다. `python examples/local_quickstart.py`는 모델이나 브라우저 없이 합성 레코드 두 개를 검증합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
verboisy --help
```

키는 [.env.example](https://github.com/EmanueleTorrisi/verboisy/blob/main/.env.example)을 참고하여 개인 환경이나 `.env`에 보관하고 커밋하지 마세요. 셸 예시는 POSIX 문법이며 Windows에서는 동등한 방법으로 환경 변수를 설정해야 합니다.

```bash
verboisy setup
verboisy model-config
```

`model-config`는 설정과 자격 증명의 존재 여부만 표시하고 키 값은 노출하지 않습니다. 결정론적 로컬 준비는 모델이나 브라우저가 필요 없습니다. [공급자](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/providers.md)와 [검증](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/validation.md)을 참조하세요.

## 웹 조사와 API

```bash
verboisy run \
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
verboisy run \
  --goal "제공된 스키마에 따라 로컬 관측 데이터를 준비하고 원본 값을 유지해 주세요" \
  --dataset-file 'jsonl=/srv/verboisy입력/관측데이터.jsonl' \
  --schema 관측스키마.json \
  --mass-unit source --length-unit source --date-format source \
  --export 관측데이터.json
```

디렉터리와 스키마 파일이 있어야 합니다. 모델 자격 증명은 파일 시스템 접근 권한을 주지 않습니다. 선언된 HTTP 출처는 제한된 다운로드, 리디렉션 정책, DNS 고정 및 출처별 비밀 값을 사용합니다. 출처의 위치와 모델 실행 위치는 독립적입니다. 원격 모델로 관찰 내용이 전송될 수 있으므로 기밀 자료를 처리하기 전에 전송, 로그, 네트워크 및 보관 정책을 확인하세요.

## 대용량 데이터셋

```bash
verboisy stream \
  --database 관측스트림.db \
  --dataset-file 'jsonl=/srv/verboisy입력/관측데이터.jsonl' \
  --schema 관측스키마.json \
  --export 관측데이터.jsonl
```

스트리밍 원장은 불변 원본 청크와 트랜잭션 진행 상황을 보존합니다. `stream-status`로 작업을 확인하고 `stream --resume 작업ID`로 저장된 작업을 재개합니다. `StreamLedger`는 페이지 단위 읽기를 제공합니다.

Linux/Python 3.12의 JSONL 측정에서는 **1,000,000행**, **1,105,888,890바이트**를 준비·출력했고 최대 RSS는 **89.15 MiB**, 경과 시간은 **130.81초**였습니다. 원본 삭제 후 복구와 출력 무결성도 검증했습니다. 이는 특정 작업의 측정이며 보편적인 속도나 메모리 보장은 아닙니다. [스트리밍](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/streaming.md)과 [벤치마크](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/benchmarks.md)를 참조하세요.

## 제안, 재개와 근거

```bash
verboisy changes --run-id 실행ID
verboisy status --run-id 실행ID
verboisy run --resume 실행ID
```

`--resume`은 기존 요구를 유지하고 제안을 거절합니다. `--okresume`은 저장된 변경만 승인합니다. 제안은 타입, 열 또는 검색 범위를 바꿀 수 있습니다. 재개는 사용량을 초기화하거나 출처 권한을 암묵적으로 확대하지 않습니다.

범위는 범위로 유지합니다. 하한을 정확한 값이나 만들어 낸 상한으로 바꾸지 않습니다. 숫자형 min/max 열에는 적절한 스키마가 필요합니다. 기본 표시는 킬로그램, 미터, 일/월/년이며 대안을 명시해도 원본 근거를 보존합니다. 시계열 진단은 누락된 관찰을 보간하거나 모호한 현지 시각을 추측하지 않습니다.

이동 가능한 출력은 근거, 관련 이벤트, 출력 출처 기록과 해당하는 캡처 자료를 포함합니다. 그룹은 기여 레코드를 식별합니다. 체크섬은 매니페스트와 바이트 일치 여부를 확인하며 사실성이나 독립적인 진본성을 증명하지 않습니다. [출처 기록](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/proof.md)을 참조하세요.

## 아키텍처와 문서

Python은 오케스트레이션, 계약, 어댑터, CLI 및 SQLite 원장을 담당합니다. 선택적 C++17 구성 요소는 Python 참조 구현을 유지하며 특정 근거 비교를 가속합니다. 테스트와 CI는 플랫폼, 브라우저, 복구 및 무결성을 검증하고 문장·분기의 완전한 커버리지를 요구합니다. 실제 조사 품질과 공급자 호환성은 별도 평가가 필요합니다.

[CLI](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/cli.md) · [API](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/api.md) · [계약](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/contracts.md) · [식별](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/smartid.md) · [수집](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/ingestion.md) · [표시](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/presentation.md) · [의미](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/research-semantics.md) · [설계](https://github.com/EmanueleTorrisi/verboisy/blob/main/ARCHITECTURE.md) · [변경 기록](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md)

## 라이선스, 데모와 상업 문의

Verboisy는 독점 소프트웨어로 **오픈소스가 아닙니다**. 영문 LICENSE가 공식 조건이며 이 번역은 권리를 변경하지 않습니다. 적용되는 버전은 소프트웨어와 함께 제공되는 [LICENSE](https://github.com/EmanueleTorrisi/verboisy/blob/main/LICENSE)에 명시되어 있습니다. 제삼자 구성 요소는 각자의 라이선스를 유지합니다. 실행, 테스트, 수정, 통합, 배포 및 호스팅에는 별도 서면 허가가 필요합니다.

데모, 평가, 사내·기업 라이선스, 제휴 및 향후 유급 협업은 **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** 으로 문의하세요. 작업 흐름, 출처, 규모, 환경을 설명하고 자격 증명이나 기밀 자료는 보내지 마세요. 가격, 지원 및 권리는 개별 합의합니다. [라이선스](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/licensing.md)와 [상업 문의](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)를 참조하세요.

## 피드백과 협업

**Emanuele Torrisi**가 Verboisy를 만들고 유지하며 현재 유일한 개발자입니다. [버그 보고와 기능 요청](https://github.com/EmanueleTorrisi/verboisy/issues)을 환영합니다. 취약점은 [보안 정책](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/SECURITY.md)에 따라 비공개로 보고하세요.

요청하지 않은 코드 기여는 받지 않습니다. 유료 협업은 범위, 보수, 기밀 유지와 지식재산권에 대한 사전 합의가 필요합니다. 버전 변경은 [변경 기록](https://github.com/EmanueleTorrisi/verboisy/blob/main/CHANGELOG.md), 0.1.0에서 1.0.0까지의 발전은 [버전 역사](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)에 기록합니다. [참여 정책](https://github.com/EmanueleTorrisi/verboisy/blob/main/.github/CONTRIBUTING.md)과 [저작권](https://github.com/EmanueleTorrisi/verboisy/blob/main/COPYRIGHT.md)을 확인하세요.
## 실제 워크플로 예제

[연구 기관 목록](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/research_catalog/README.md) ·
[대규모 로컬 관측 데이터 처리](https://github.com/EmanueleTorrisi/verboisy/blob/main/examples/streaming_observations/README.md) ·
[버전 이력: 0.1.0–1.0.0](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/development-roadmap.md)


## 데이터 계약과 검증 범위

일반 출력의 `id`는 생성된 메타데이터용입니다. 원본 ID는 명시적으로 `source_id`에 투영해야 하며, 중첩 ID와 스트리밍 ID는 유지됩니다. 누락된 선택 필드는 그대로 누락되고 명시적 null은 유지됩니다. 스트리밍은 개별 행을 검증하고 지원되지 않는 배열 전체 제약은 거부합니다. 일시 중지된 준비 작업은 종료 코드 2를 반환합니다. 과거 측정 결과는 각 보고서에 기록된 소스 코드와 실행 환경에 적용됩니다.

[과거 검증 결과](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/results/offline-validation.json) · [릴리스 근거 및 승인](https://github.com/EmanueleTorrisi/verboisy/blob/main/evals/release-matrix.json).


## 상업 계약을 선택하는 이유

이 저장소에는 **소스 코드를 열람하고 검토하기 위한 Verboisy 공개 에디션**이 포함되어 있습니다. 상업용 고객에게는 **추가 기능을 갖추고 별도로 유지보수되는 에디션**을 제공합니다. 이러한 추가 기능은 이 저장소에서 배포하지 않습니다.

[에디션 비교](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/commercial.md)에는 각 에디션의 범위, 배포 방식 및 서비스가 설명되어 있습니다. 제공되는 추가 기능은 상업용 릴리스 노트와 서명된 계약에 명시합니다. 공개 저장소도 계속 업데이트됩니다.

제공 기능, 사용 권한, 지원, 업데이트 제공 범위, 요금 및 납품 일정은 서명된 계약에 명시합니다.

| 목표 | 계약으로 정할 범위 |
| --- | --- |
| 일상 업무에 사용 | 합의된 사용자와 환경에 대한 서면 실행 및 내부 사용 권한 |
| 제품에 통합 | 용도에 맞는 수정·통합·배포 권한 |
| 초기 작업 감소 | 온보딩, 스키마 설계, 대표 데이터 평가 |
| 비공개 인프라에서 운영 | 배포 환경 검토와 허가된 소스 통합 |
| 유지보수와 지원 계획 | 계약에 명시된 업데이트, 지원 범위, 응답 시간 |

업무 흐름, 배포 요구 사항 및 인수 기준에 맞춰 에디션과 서비스를 선택합니다. 계약은 제공 항목과 책임 범위를 명확하게 정합니다.

[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)

[설치](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/installation.md) · [릴리스와 평가](https://github.com/EmanueleTorrisi/verboisy/blob/main/docs/release.md)
