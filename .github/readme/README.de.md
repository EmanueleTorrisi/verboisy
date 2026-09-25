# Verboisy — Kurzanleitung

Verboisy recherchiert mit Browser und Sprachmodell, validiert Datensätze und speichert sie in SQLite.

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

Fortsetzen stellt Daten, Verlauf und die zuletzt gespeicherte URL wieder her, jedoch keine Cookies oder JavaScript-Zustände. Ein erreichtes Limit bedeutet unvollständig. Das frühere GIF ist illustrativ. Lokale Tests belegen weder Modellgenauigkeit noch Produktionsreife.

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
