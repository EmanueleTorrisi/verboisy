# Verboisy — 快速开始

Verboisy 使用浏览器和模型进行网页研究，验证记录后保存到 SQLite。

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

恢复运行会载入数据、历史和最后保存的 URL，但不会恢复 Cookie 或 JavaScript 状态。达到限制时运行仍为未完成。旧 GIF 仅用于说明。本地测试不能证明模型准确性或生产环境适用性。

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
