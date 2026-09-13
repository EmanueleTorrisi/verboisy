<p align="center">
  <img src="../../logo.png" alt="verboisy" width="300" />
</p>
<p align="center">
  <strong align="center">자율적인 웹 리서치 및 구조화된 스크랩-to-JSON 에이전트.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
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

## 설치 방법:

```bash
pip install verboisy
playwright install --with-deps chromium
```

## 설정 방법:

.env.example 파일을 .env로 복사하고 API 키를 설정하세요:

-> OPENAI_API_KEY=sk-...

-> LITELLM_MODEL=gpt-4o

## 사용 방법:

Verboisy는 간단한 명령줄 인터페이스를 통해 작동합니다.
쉬운 영어로 된 목표와 반환받고자 하는 정확한 데이터 구조를 정의하는 JSON 스키마를 제공하면 됩니다.

전체 예시 명령어는 다음과 같습니다:
```bash
verboisy run \
  --goal "Y Combinator W24의 최신 AI 스타트업을 찾아보세요" \
  --schema examples/yc_startups/schema.json \
  --export result.json
```

명령어 분석:

*run*: 자율 에이전트를 시작하는 기본 명령어입니다.

*--goal* (또는 -g): 에이전트에게 무엇을 찾고 어디로 가야 하는지 정확히 알려줍니다. 가능한 한 구체적으로 작성하세요.

*--schema* (또는 -s): 사용자 지정 JSON 스키마의 파일 경로입니다. 이 파일은 Verboisy에게 어떤 데이터 필드를 추출해야 하는지(예: 회사명, 웹사이트, 설명) 정확히 알려줍니다.

*--export* (또는 -e): (선택 사항) 최종 추출된 데이터를 저장할 파일 경로입니다. .json 및 .csv 형식을 지원합니다.

Enter 키를 누르면, Verboisy가 헤드리스 브라우저를 실행하고, 자율적으로 웹을 탐색하며, 페이지 DOM을 분석하고, 스키마와 일치하는 데이터를 추출하여 result.json 파일에 저장합니다.


----------------------------------------------------------------------------------------
**Verboisy는 Emanuele Torrisi가 작성했으며 BSD 2-Clause 라이선스에 따라 배포됩니다.**
