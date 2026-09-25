# Verboisy — クイックスタート

Verboisy はブラウザーとモデルでウェブを調査し、検証したレコードを SQLite に保存します。

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

再開時にはデータ、履歴、最後に保存した URL を復元します。Cookie や JavaScript の状態は復元しません。上限に達した実行は未完了です。以前の GIF は説明用です。ローカルテストだけではモデルの正確性や本番運用への適合性を保証できません。

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
