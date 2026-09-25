# Verboisy — Guida rapida

Verboisy esegue ricerche web con un browser e un modello, valida i record e li salva in SQLite.

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

La ripresa ripristina dati, cronologia e ultimo URL salvato; non ripristina cookie o stato JavaScript. I limiti producono un risultato incompleto. La GIF precedente è illustrativa. I test locali non dimostrano accuratezza del modello o idoneità alla produzione.

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
