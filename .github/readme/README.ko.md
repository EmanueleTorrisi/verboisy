<a id="readme-top"></a>
<p align="center">
  <img src="../../logo.png" alt="Verboisy" width="300" />
</p>
<p align="center">
  <strong>웹 리서치와 구조화된 JSON 추출을 자율적으로 수행하는 에이전트.</strong>
  <br />
  자연어로 목표를 설명하고 JSON Schema를 제공하세요. 에이전트가 탐색 경로를 직접 계획하고 페이지를 읽어 검증된 구조화 데이터를 반환합니다.
</p>

<p align="center">
  <a href="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/EmanueleTorrisi/verboisy"><img src="https://codecov.io/gh/EmanueleTorrisi/verboisy/graph/badge.svg?token=CINC6IHYF2" alt="테스트 커버리지"></a>
  <a href="https://emanueletorrisi.github.io/verboisy/"><img src="https://github.com/EmanueleTorrisi/verboisy/actions/workflows/docs.yml/badge.svg" alt="문서"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/PyPI-coming%20soon-lightgrey?style=flat" alt="PyPI: 출시 예정"></a>
  <!--<a href="https://pypi.org/project/verboisy/"><img src="https://img.shields.io/pypi/v/verboisy?style=flat" alt="PyPI version"></a>-->
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat" alt="Python 3.11+">
  <a href="../../LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="라이선스"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/style-ruff-261230?style=flat" alt="Ruff"></a>
</p>

<p align="center">
  <em>v0.1.0 | 1.0 이전 버전이며 활발히 개발 중입니다. 1.0까지는 마이너 버전 사이에 호환성을 깨는 변경이 발생할 수 있습니다.</em>
</p>

<p align="center">
  <a href="../../README.md" title="English" aria-label="English">🇬🇧</a> ·
  <a href="README.it.md" title="Italiano" aria-label="Italiano">🇮🇹</a> ·
  <a href="README.de.md" title="Deutsch" aria-label="Deutsch">🇩🇪</a> ·
  <a href="README.zh-CN.md" title="简体中文" aria-label="简体中文">🇨🇳</a> ·
  <a href="README.fr.md" title="Français" aria-label="Français">🇫🇷</a> ·
  <a href="README.es.md" title="Español" aria-label="Español">🇪🇸</a> ·
  <strong title="한국어" aria-label="한국어">🇰🇷</strong> ·
  <a href="README.ja.md" title="日本語" aria-label="日本語">🇯🇵</a>
</p>

## 목차

- [데모](#demo)
- [Verboisy를 사용하는 이유](#why-verboisy)
- [도구 비교](#compared-to)
- [빠른 예제](#quick-example)
- [사용 사례](#use-cases)
- [작동 방식](#how-it-works)
- [설치](#installation)
- [설정](#configuration)
- [사용법](#usage)
- [Docker](#docker)
- [알려진 제한 사항](#known-limitations)
- [책임 있는 사용](#responsible-use)
- [문서](#documentation)
- [기여](#contributing)
- [보안](#security)
- [라이선스](#license)

<a id="demo"></a>

## 데모

[과거 애니메이션](../../docs/demo.gif)은 설명용일 뿐이며 제품이 검증되었다는 증거가 아닙니다. 제공된 녹화 영상은 실행 재개 기능이 구현되기 전에 제작되었습니다. [실제 라이브 데모 절차](../../docs/demo.md)를 사용해 브라우저, 모델, SQLite, 중단 및 내보내기의 실제 동작을 녹화하세요. 새 라이브 녹화는 여전히 인수 조건입니다.

이번 개정판에는 실행 가능한 오프라인 회귀 테스트와 필수 Chromium 통합 검사가 포함됩니다. 배포 전 [검증 및 릴리스 검사](../../docs/validation.md)를 읽어 주세요. 이 내용은 운영 환경에 바로 사용할 준비가 되었다는 주장이 아닙니다.

<a id="why-verboisy"></a>

## Verboisy를 사용하는 이유

- **선택자가 아닌 목표 중심.** 자연어로 목표를 설명하세요. 플래너가 실제로 표시된 페이지를 보고 다음 클릭, 스크롤 또는 읽기 작업을 결정합니다. 모델은 관찰한 DOM에 적응하려고 하지만 사이트가 개편되면 실행이 실패할 수 있습니다.
- **대충 추출하지 않고 스키마부터 적용.** 모든 레코드를 JSON Schema와 대조한 뒤 Pydantic 모델로 감싸 저장합니다. 검증은 구조와 제약 조건을 검사하지만 사실의 정확성을 입증하지는 않습니다.
- **모델과 인프라를 직접 선택.** [LiteLLM](https://github.com/BerriAI/litellm)을 통해 OpenAI, Anthropic 또는 로컬 Ollama 모델을 사용할 수 있으며 환경 변수 하나로 전환합니다. 불투명한 호스팅 서비스가 아니라 사용자의 컴퓨터나 서버에서 실행됩니다.
- **처음부터 재개를 고려한 설계.** 검증된 레코드는 다음 후보를 처리하기 전에 SQLite에 확정 저장됩니다. `verboisy run --resume`(Python에서는 `run(resume=True)`)은 가장 최근의 미완료 실행을 이어 갑니다. 이전에 저장한 결과는 단계 도중 중단되어도 유지됩니다. 재개 시 저장된 진행 상황과 마지막 체크포인트 URL은 복원하지만 브라우저 세션 상태는 복원하지 않습니다.

이 루프에는 비동기 Playwright(창 표시 또는 헤드리스 Chromium), 원시 HTML 덤프 대신 LLM 컨텍스트 창에 맞춘 DOM 정리, JSON/CSV 내보내기가 포함됩니다. SQLite 데이터베이스를 직접 조회할 수도 있습니다.

<a id="compared-to"></a>

## 도구 비교

Verboisy는 자율 브라우저 에이전트와 스키마 검증 추출기를 결합합니다. 비슷한 도구는 둘 중 하나를 잘 처리하는 경우가 많으며 Verboisy는 두 기능 모두를 위해 설계되었습니다.

| | Verboisy | [Browser Use](https://github.com/browser-use/browser-use) | [Firecrawl](https://github.com/firecrawl/firecrawl) | [Crawl4AI](https://github.com/unclecode/crawl4ai) |
| --- | --- | --- | --- | --- |
| 입력할 내용 | 목표 **및** JSON Schema | 목표 | URL + 프롬프트 또는 스키마 | 크롤링 규칙 + 프롬프트 |
| 탐색 | 플래너가 클릭 선택 | 플래너가 클릭 선택 | 크롤링 / 사이트맵 | 크롤링 |
| 검증 | 쓰기 전에 JSON Schema + Pydantic | 사용자 코드 | 선택적 추출 스키마 | 사용자 코드 |
| 영속성 | 레코드별 SQLite 저장, `--resume` | 메모리 / 사용자 코드 | API 또는 자체 DB | 사용자 코드 |
| 실행 위치 | 사용자 컴퓨터 | 사용자 컴퓨터 | 호스팅 또는 자체 호스팅 | 사용자 컴퓨터 |

URL을 이미 알고 Markdown만 필요하다면 Firecrawl이나 Crawl4AI가 더 간단합니다. 범용 컴퓨터 조작 에이전트가 필요하고 데이터 검증은 나중에 할 예정이라면 Browser Use가 적합합니다. 에이전트가 직접 찾아낸 결과를 스키마에 맞는 행으로 받아야 한다면 Verboisy의 사용 목적에 해당합니다.

<a id="quick-example"></a>

## 빠른 예제

스키마는 JSON Schema 형식입니다. 레코드 목록의 최상위 형식은 `"array"`이며 `"items"`가 각 행의 객체 구조를 정의합니다.

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "website": { "type": "string" },
      "description": { "type": "string" },
      "batch": { "type": "string" }
    },
    "required": ["name", "website"]
  }
}
```

Verboisy는 실행 시 스키마에서 Pydantic 모델을 생성하고, 일치하지 않는 행이 SQLite에 들어가기 전에 거부합니다.

명령줄 인터페이스(CLI):

```bash
verboisy run \
  --goal "Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

Python에서 같은 실행을 수행하려면:

```python
from verboisy import run

result = run(
    goal="Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기",
    schema="examples/yc_startups/schema.json",
    export="result.json",
)

print(result.run_id, len(result.records))
for row in result.records:
    print(row["name"], row["website"])
```

다음은 가능한 예시 출력 구조입니다.

```json
[
  {
    "name": "Marrow",
    "website": "https://marrow.example.com",
    "description": "운영 AI 에이전트를 위한 스테이징 환경.",
    "batch": "F26"
  },
  {
    "name": "Kiln Trace",
    "website": "https://kilntrace.example.com",
    "description": "에이전트 워크플로의 지연 시간과 비용 디버깅.",
    "batch": "F26"
  }
]
```

*(예시 출력: 실제 결과는 실행 시점에 페이지에 표시된 내용에 따라 달라집니다. 예제 이름에는 의도적으로 `.example.com`을 사용했습니다.)*

실행 도중 프로세스가 중단되면 저장된 행을 다시 처리하지 않고 이어서 실행할 수 있습니다.

```bash
verboisy run --resume
```

```python
result = run(resume=True)
```

<a id="use-cases"></a>

## 사용 사례

Verboisy는 반복해서 실행할 가치가 있는 리서치 작업을 위해 만들어졌습니다.

- **경쟁사 및 시장 정보:** 경쟁사의 가격, 제품 페이지 및 공지를 수동으로 확인하지 않고 정기적으로 추적합니다.
- **B2B 잠재 고객 조사:** 회사 이름 목록을 CRM에 가져올 수 있는 구조화된 기업 특성 및 기술 스택 기록으로 변환합니다.
- **전자상거래 및 소매 모니터링:** JavaScript 사용량이 많은 쇼핑몰의 상품 목록과 가격 변화를 살펴봅니다.
- **리서치 운영(ResOps):** 수백 개 대상에 같은 쿼리 패턴을 정기적으로 실행합니다.
- **RAG / 지식 베이스 수집:** 수동으로 고른 컨텍스트 대신 출처가 포함된 구조화 레코드를 검색 파이프라인에 전달합니다.

모든 사례는 빠른 예제와 동일한 목표 + 스키마 방식이며 대상 사이트와 데이터 구조만 다릅니다.

<a id="how-it-works"></a>

## 작동 방식

Verboisy는 플래너가 충분한 데이터를 얻었다고 판단하거나 허용된 단계 수를 모두 사용할 때까지 **계획 → 실행 → 관찰 → 추출** 루프를 반복합니다.

```mermaid
flowchart LR
    F[run --resume] --> A
    A[다음 작업 계획] -->|탐색 또는 클릭| B[브라우저가 실행]
    A -->|추출| C[DOM을 JSON으로 변환]
    B --> D[LLM용 DOM 정리]
    D --> A
    C --> E[SQLite에 저장]
    A -->|완료| E
```

추출된 레코드는 검증을 통과하는 즉시 `run_id`와 함께 SQLite에 확정 저장됩니다. 요청 속도 제한, 충돌 또는 프로세스 종료로 루프가 중단되면 `verboisy run --resume`(또는 `run(resume=True)`)이 해당 실행의 목표, 스키마, 저장된 행, 기록 및 마지막 체크포인트 URL을 다시 불러와 계속 진행합니다. `--resume <id>`는 특정 실행을, ID 없는 `--resume`은 최근 미완료 실행을 선택합니다.

`--export`는 실행이 끝날 때 파일을 기록하며 재개한 실행이 완료된 경우도 같습니다. 그전까지 부분 결과는 `SQLITE_DB_PATH`에 보관됩니다.

각 모듈의 전체 설명은 [`ARCHITECTURE.md`](../../ARCHITECTURE.md)를 참고하세요.

<a id="installation"></a>

## 설치

Python 3.11 이상이 필요합니다.

아직 PyPI에 등록되지 않았습니다. 소스에서 설치하세요.

```bash
git clone https://github.com/EmanueleTorrisi/verboisy.git
cd verboisy
python -m pip install -e .
python -m playwright install chromium
```

첫 릴리스 이후에는 다음 명령을 사용할 수 있습니다.

```bash
python -m pip install verboisy
python -m playwright install chromium
```

Chromium은 설정 단계에서 설치합니다. Verboisy는 실행 중에 브라우저를 다운로드하거나 시스템 패키지 관리자를 실행하지 않습니다. 설치와 실행에 동일한 OS 사용자와 Python 환경을 사용하세요. Linux에서는 `python -m playwright install --with-deps chromium`으로 브라우저와 시스템 의존성을 설치합니다(시스템 패키지에는 관리자 권한이 필요합니다). Poetry를 사용하는 경우 `poetry run playwright install --with-deps chromium`을 실행하세요.

<a id="configuration"></a>

## 설정

`.env.example`을 `.env`로 복사하세요. 모든 설정은 `utils/config.py`에서 Pydantic을 통해 불러오며 지정하지 않은 항목은 아래 기본값을 사용합니다.

```bash
# 필수: 하나 이상의 LLM 제공업체
OPENAI_API_KEY=sk-your-api-key-here
# ANTHROPIC_API_KEY=sk-ant-your-api-key-here

# LiteLLM 모델 라우팅(예: gpt-4o, claude-sonnet-5, ollama/llama3)
LITELLM_MODEL=gpt-4o

SQLITE_DB_PATH=verboisy.db
VERBOISY_LOG_LEVEL=INFO
VERBOISY_HEADLESS=true
```

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | - | OpenAI 인증 정보. Anthropic 또는 로컬 모델을 사용하지 않으면 필수입니다. |
| `ANTHROPIC_API_KEY` | - | OpenAI 대신 사용하는 Anthropic 인증 정보. |
| `LITELLM_MODEL` | `gpt-4o` | [LiteLLM](https://github.com/BerriAI/litellm)이 지원하는 모델 문자열. |
| `MAX_TOKENS` | `4096` | 계획 또는 추출 호출당 최대 토큰 수. |
| `TEMPERATURE` | `0.0` | 플래너의 샘플링 온도. |
| `VERBOISY_HEADLESS` | `true` | Chromium을 헤드리스로 실행합니다. `false`이면 브라우저 창을 볼 수 있습니다. |
| `BROWSER_TIMEOUT_MS` | `30000` | 페이지별 탐색 시간 제한(ms). |
| `USER_AGENT_ROTATION` | `true` | 브라우저 컨텍스트 생성 시 User-Agent를 선택하며 요청마다 변경하지 않습니다. |
| `SQLITE_DB_PATH` | `verboisy.db` | 실행과 추출 레코드를 저장하는 경로. |
| `VERBOISY_LOG_LEVEL` | `INFO` | 표준 Python 로그 수준. `DEBUG`는 플래너의 모든 단계를 출력합니다. |

LLM 제공업체에는 사용자가 직접 비용을 지불합니다. 계획 및 추출 호출에는 `MAX_TOKENS`(기본 4096)가 적용되고 `TEMPERATURE`는 0.0입니다. 호출 횟수는 탐색, 추출 및 재시도에 따라 달라집니다. 호스팅된 사용량 측정기는 없습니다.

<a id="usage"></a>

## 사용법

### CLI

```bash
verboisy run \
  --goal "Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

명령은 `run_id`를 로그에 출력하며 SQLite에도 저장합니다. 단계 예산을 모두 쓰면 미완료 결과와 종료 코드 2를 반환합니다. 일반 오류는 1, Ctrl-C는 130입니다. FINISH와 컬렉션 검증 성공이 모두 충족되어야 완료됩니다. 이 ID를 사용해 나중에 실행을 재개할 수 있습니다.

| 옵션 | 단축형 | 필수 여부 | 설명 |
| --- | --- | --- | --- |
| `--goal` | `-g` | `--resume`이 없을 때 필수 | 무엇을 어디에서 찾을지 자연어로 구체적으로 설명합니다. |
| `--schema` | `-s` | `--resume`이 없을 때 필수 | 추출할 필드의 JSON Schema 경로. 최상위는 레코드 `object`로 구성된 `array`입니다. |
| `--export` | `-e` | 아니요 | 출력 경로. `.json`과 `.csv`를 지원하며 실행 종료 시 기록합니다. |
| `--resume` | `-r` | 아니요 | 실행을 재개합니다. `--resume`만 사용하면 `SQLITE_DB_PATH`의 최근 미완료 실행을, `--resume <id>`는 지정한 실행을 이어 갑니다. 목표와 스키마는 저장된 실행에서 불러오지만 `--export`와 브라우저 창 표시 여부는 변경할 수 있습니다. |

전체 옵션은 `verboisy run --help`로 확인하세요.

추가 옵션으로 `--max-steps/-m`과 `--headless/--headed`가 있습니다. 재개할 때 단계 허용량은 새로 부여되지만 저장된 카운터는 누적됩니다. 고유한 실행 ID 접두사도 사용할 수 있습니다. 완료된 실행은 브라우저나 모델을 호출하지 않고 다시 내보낼 수 있습니다. 내보내기 오류는 0이 아닌 종료 코드를 반환하므로 이 방식으로 다시 시도할 수 있습니다. 결과가 비어 있어도 출력 파일을 만듭니다.

<a id="resume"></a>

### 실행 재개

```bash
# verboisy.db에서 최근 미완료 실행 재개
verboisy run --resume

# 특정 실행 재개
verboisy run --resume 7f3a2c1b --export result.json
```

중단 후 같은 페이지를 다시 읽거나 추출할 수 있습니다. 정규화한 내용이 동일한 행은 같은 실행에 중복 삽입하지 않습니다. 쿠키, 열린 탭, 스크롤 위치, 일시적인 JavaScript 상태는 복원하지 않습니다. 미완료 실행이 없으면 확인한 데이터베이스 이름을 포함한 오류를 출력하고 0이 아닌 종료 코드로 끝납니다.

### Python

`run()`은 동기식 공개 API입니다. Notebook 또는 비동기 애플리케이션에서는 `await arun(...)`을 사용하세요. CLI는 이 API를 얇게 감싼 형태입니다.

```python
from pathlib import Path
from verboisy import RunResult, run

result: RunResult = run(
    goal="Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기",
    schema="examples/yc_startups/schema.json",  # 경로, Path 또는 dict
    export="result.json",
)

print(result.run_id)
print(result.records[0]["name"])
```

파일 없이 딕셔너리로 스키마 전달하기:

```python
result = run(
    goal="Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기",
    schema={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "website": {"type": "string"},
                "description": {"type": "string"},
                "batch": {"type": "string"},
            },
            "required": ["name", "website"],
        },
    },
)
```

실행 재개:

```python
from verboisy import run

# 최근 미완료 실행
result = run(resume=True)

# 특정 실행을 재개하고 완료 시 내보내기
result = run(resume=result.run_id, export="result.json")
```

함수 시그니처:

```python
def run(
    *,
    goal: str | None = None,
    schema: str | Path | dict | None = None,
    export: str | Path | None = None,
    resume: bool | str = False,
    headless: bool | None = None,
    max_steps: int | None = None,
    config: Settings | None = None,
) -> RunResult: ...
```

`RunResult` 필드:

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `run_id` | `str` | SQLite에 저장된 고정 ID. `run(resume=...)`에 전달합니다. |
| `records` | `list[dict]` | 현재까지 이 실행에서 검증된 모든 행. |
| `export_path` | `Path \| None` | `--export` / `export=`를 지정했고 실행이 끝났다면 내보낸 파일 경로. |
| `db_path` | `Path` | 사용한 SQLite 파일. |
| `completed` | `bool` | FINISH 이후 컬렉션 검증까지 성공하면 `True`. |
| `status` | `str` | 정상 반환 시 COMPLETED 또는 PAUSED. |
| `stop_reason` | `str \| None` | 호출이 중지된 이유. |

규칙:

- 새 실행: `goal`과 `schema`가 필수이며 `resume`은 생략하거나 `False`로 설정합니다.
- 재개: `resume=True` 또는 `resume="<id>"`; `goal` / `schema`는 선택 사항이며 저장된 실행에 이미 있으면 무시됩니다.
- `headless=None`은 `VERBOISY_HEADLESS`를 사용합니다. `True` / `False`로 이번 호출에서만 덮어쓸 수 있습니다.

<a id="watching-a-run"></a>

### 실행 과정 보기

```bash
VERBOISY_HEADLESS=false VERBOISY_LOG_LEVEL=DEBUG \
  verboisy run \
    --goal "Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기" \
    --schema examples/yc_startups/schema.json \
    --export result.json
```

스키마 세부 사항: 루트는 객체 배열 또는 단일 레코드 객체의 스키마일 수 있습니다. 기존 프로퍼티 맵도 계속 지원합니다. Draft 2020-12 검증은 중첩 타입, 필수/선택/null 차이, enum, 패턴, 숫자 범위, additionalProperties 및 표준 형식을 다룹니다. 로컬 스키마 조각 참조만 허용합니다. minItems 같은 컬렉션 제약은 완료 전에 저장된 모든 행을 대상으로 검사합니다. JSON 내보내기는 값을 유지하고 CSV는 수식처럼 보이는 텍스트 앞에 작은따옴표를 붙이며 중첩 값은 JSON으로 인코딩합니다.

## Docker

```bash
# 먼저 .env를 만들고 설정합니다.
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec verboisy verboisy run \
  --goal "Y Combinator 2026년 가을 배치(F26)의 AI 스타트업 찾기" \
  --schema examples/yc_startups/schema.json \
  --export /data/result.json
docker compose -f docker/docker-compose.yml cp verboisy:/data/result.json ./result.json
```

컨테이너는 권한이 없는 사용자로 실행되고 Compose를 통해 `../.env`를 읽습니다. 이름이 지정된 볼륨은 재시작 후에도 `/data/verboisy.db`와 내보낸 파일을 유지합니다. 이미지에는 예제가 포함됩니다. Chromium 샌드박스 지원 여부는 대상 컨테이너 호스트에서 테스트해야 하며 기본값은 활성화입니다. 감사 환경에서는 Docker 빌드와 배포를 실행하지 않았습니다.

<a id="additional-configuration"></a>

## 추가 설정

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| LITELLM_API_KEY | 설정되지 않음 | 다른 제공업체/프록시의 명시적 인증 정보 |
| LITELLM_API_BASE | 설정되지 않음 | 로컬 모델을 포함한 명시적 LiteLLM 엔드포인트 |
| MAX_STEPS | 20 | 호출당 작업 허용량. CLI/API에서 덮어쓸 수 있음 |
| MAX_TOTAL_TOKENS | 1000000 | 로컬 요청 예산: 프롬프트 바이트와 시도별 예약 응답 토큰의 합. 정확한 청구 상한은 아님 |
| LLM_TIMEOUT_SECONDS | 60 | 모델 요청 1회의 시간 제한 |
| LLM_RETRIES | 2 | 일시적인 실패 시 재시도 횟수. 잘못된 JSON은 재시도하지 않음 |
| RUN_TIMEOUT_SECONDS | 900 | 호출 1회의 시간 제한 |
| MAX_DOM_CHARS | 20000 | 정리된 페이지 컨텍스트의 글자 수 제한 |
| ACTION_DELAY_SECONDS | 0.5 | 작업 사이의 대기 시간 |
| BROWSER_SANDBOX | true | Chromium 샌드박스 활성화 |
| ALLOW_PRIVATE_NETWORK | false | 내부/루프백 대상 명시적으로 허용 |
| ALLOWED_DOMAINS | [] | 정확히 허용할 대상 호스트 이름의 JSON 배열. 빈 배열은 공개 호스트를 뜻함 |

설정은 공개 API 호출마다 새로 불러옵니다. `.env`의 OpenAI 및 Anthropic 키는 선택한 제공업체로 명시적으로 라우팅됩니다. 로컬 모델에는 `LITELLM_API_BASE`를 사용할 수 있습니다. 호출 도중 전역 변수를 이용해 제공업체나 예산을 변경하지 마세요.

<a id="known-limitations"></a>

## 알려진 제한 사항

이번 개정판에서는 문서화된 주요 실행 경로를 수정했지만 실제 배포 플랫폼에서 라이브 모델과 실제 브라우저를 통한 인수 테스트가 여전히 필요합니다. 오프라인 테스트만으로 자율 리서치의 정확성을 보증할 수는 없습니다.

- 재개 기능은 마지막 저장 URL만 복원하며 브라우저 세션 전체는 복원하지 않습니다. SPA 페이지 이동, 인증 세션 및 진행 중이던 작업에는 새 탐색이 필요할 수 있습니다.
- 사설망 차단과 도메인 검사는 심층 방어 수단입니다. DNS 리바인딩, 브라우저 코드, 프롬프트 인젝션에 대응하려면 배포 격리 및 외부 송신 제어가 필요합니다.
- 스키마 작성자는 신뢰할 수 있다고 가정합니다. 악의적인 정규식과 재귀 스키마에 대한 리소스 격리는 없습니다.
- DOM 컨텍스트에는 크기 제한이 있습니다. 긴 페이지에서는 스크롤이나 페이지 이동이 필요하며 데이터가 누락될 수 있습니다.
- 모델의 FINISH는 모델이 중지하기로 했다는 뜻일 뿐입니다. 사실 정보가 모두 수집되었는지 별도로 확인하세요.
- 로컬 데이터베이스당 협조적으로 동작하는 호출 하나만 지원합니다. 기존 중복 데이터는 마이그레이션 시 유지하며 과거의 잘못된 COMPLETED 상태를 추론만으로 수정할 수는 없습니다.

기타 제한 사항:

- **계정이나 호스팅 작업 기록 없음:** 단일 사용자용입니다. 실행 ID는 대시보드가 아닌 로컬 SQLite 파일에 저장됩니다.
- **내장 스케줄링 없음:** 수동 실행 또는 자체 cron/오케스트레이터를 사용하세요. `--resume`은 충돌과 요청 속도 제한 후의 복구 기능이지 스케줄러가 아닙니다.
- **호스팅 HTTP API 없음:** 현재 인터페이스는 CLI, `verboisy.run()`, Docker 이미지입니다.
- **강력한 봇 차단 사이트에서 불안정:** 일부 대상은 재시도나 수동 개입이 필요합니다.

이 제한이 사용 사례를 막고 있나요? [이슈를 등록](https://github.com/EmanueleTorrisi/verboisy/issues)해 먼저 고쳐야 할 항목을 알려 주세요.

<a id="responsible-use"></a>

## 책임 있는 사용

Verboisy는 사용자를 대신하여 실제 브라우저를 조작합니다. 대상 사이트별 서비스 약관, `robots.txt`, 요청 속도 제한 및 관할 지역의 법률을 준수할 책임은 사용자에게 있습니다. 권한이 없는 인증이나 접근 제어를 우회하는 용도로 사용하지 마세요.

<a id="documentation"></a>

## 문서

전체 설정 참조와 API 세부 사항을 포함한 문서는 **[emanueletorrisi.github.io/verboisy](https://emanueletorrisi.github.io/verboisy/)**에 공개되어 있습니다.

<a id="contributing"></a>

## 기여

기여를 환영합니다. 로컬 설정 및 코딩 규칙은 [`CONTRIBUTING.md`](../CONTRIBUTING.md)를 참고하고 [행동 강령](../CODE_OF_CONDUCT.md)을 지켜 주세요. 처음 시작한다면 [`good first issue`](https://github.com/EmanueleTorrisi/verboisy/labels/good%20first%20issue) 태그가 붙은 이슈를 확인하세요.

<a id="security"></a>

## 보안

취약점을 발견했나요? 공개 이슈를 만들지 말고 [비공개 취약점 보고](https://github.com/EmanueleTorrisi/verboisy/security/advisories/new)를 이용하거나 [`SECURITY.md`](../SECURITY.md)를 참고하세요.

<a id="license"></a>

## 라이선스

BSD 2-Clause: 전문은 [`LICENSE`](../../LICENSE)를 참조하세요.

---

<p align="center">
  제작자: <a href="https://github.com/EmanueleTorrisi">Emanuele Torrisi</a> · <a href="#readme-top">맨 위로 ↑</a>
</p>

Search API and bounded browser recovery: [configuration and limits (English)](../../docs/search-and-recovery.md).
