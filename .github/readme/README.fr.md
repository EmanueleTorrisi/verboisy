# Verboisy — Démarrage rapide

Verboisy effectue des recherches avec un navigateur et un modèle, valide les données et les enregistre dans SQLite.

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

La reprise restaure les données, l’historique et la dernière URL sauvegardée, mais pas les cookies ni l’état JavaScript. Atteindre une limite laisse l’exécution incomplète. L’ancien GIF est illustratif. Les tests locaux ne prouvent ni la précision du modèle ni l’aptitude à la production.

- [README: complete current contract](../../README.md)
- [Architecture](../../ARCHITECTURE.md)
- [API](../../docs/api.md)
- [Validation](../../docs/validation.md)
- [Authentic demo](../../docs/demo.md)

This concise translation replaces earlier examples with malformed Markdown links inside
shell commands. The complete current specification is maintained in the linked README.
