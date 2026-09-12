<p align="center">
  <img src="./logo.png" alt="verboisy" width="140" />
</p>
<p align="center">
  <strong align="center">An autonomous web research and structured scrape-to-JSON agent.</strong>
</p>
<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EmanueleTorrisi/verboisy?style=flat" alt="License"></a>
</p>


## Architecture

```mermaid
graph TD
    CLI[Typer CLI] --> Agent[Core Agent Loop]
    Agent --> Planner[LLM Planner]
    Agent --> Context[Browser Manager]
    Context --> DOM[DOM Parser & Cleaner]
    DOM --> Extractor[Extraction Engine]
    Extractor --> Pydantic[Dynamic Schema Builder]
    Pydantic --> Storage[SQLite / Exporters]
```

## Installation

pip install verboisy
playwright install --with-deps chromium

## Configuration

Copy .env.example to .env and set your API keys:

OPENAI_API_KEY=sk-...
LITELLM_MODEL=gpt-4o

## Usage

verboisy run \
  --goal "Find the latest AI startups from YCombinator W24" \
  --schema examples/yc_startups/schema.json \
  --export result.json

## License

Verboisy was written by Emanuele Torrisi and is released under the BSD 2 clause license.
