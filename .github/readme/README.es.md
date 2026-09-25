# Verboisy — Guía rápida

Verboisy investiga con un navegador y un modelo, valida los registros y los guarda en SQLite.

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

La reanudación restaura datos, historial y la última URL guardada, pero no cookies ni estado JavaScript. Agotar un límite deja la ejecución incompleta. El GIF anterior es ilustrativo. Las pruebas locales no demuestran precisión del modelo ni preparación para producción.

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
