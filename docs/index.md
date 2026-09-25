# Verboisy

Verboisy combines model-directed browser navigation, schema validation and durable
SQLite records. The CLI and Python API share one implementation.

Install the checked-out source (a published package is not assumed):

```bash
python -m pip install -e .
python -m playwright install chromium
verboisy run --help
```

Configure a LiteLLM model and its credentials before a live run. System dependencies
may be required for Chromium. Linux installations can use
`python -m playwright install --with-deps chromium` with appropriate system privileges.

The release audit, exact reproduction steps, requirement matrix, and verification
limits are in the delivered engineering report. Browser and live-model acceptance
must be checked separately from offline test coverage.

- [API](api.md)
- [Authentic demo and live acceptance](demo.md)
- [Validation and release](validation.md)
