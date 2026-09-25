# Verboisy — 빠른 시작

Verboisy는 브라우저와 모델로 웹을 조사하고 검증한 레코드를 SQLite에 저장합니다.

```bash
python -m pip install -e .
python -m playwright install chromium
verboisy run --help
```

Configure `.env` with a supported LiteLLM model and its provider credentials.
Run these commands from the repository root:

```bash
verboisy run --goal "Find AI startups in the Fall 2026 YC batch using page evidence" --schema examples/yc_startups/schema.json --export result.json
verboisy run --resume
```

```python
from verboisy import run
result = run(resume=True)
print(result.run_id, result.completed, result.records)
```

재개 시 데이터, 기록, 마지막으로 저장한 URL을 복원하지만 쿠키나 JavaScript 상태는 복원하지 않습니다. 제한에 도달하면 미완료 상태입니다. 이전 GIF는 설명용입니다. 로컬 테스트만으로 모델 정확성이나 운영 환경 적합성을 입증할 수 없습니다.

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
