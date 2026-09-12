# Verboisy Documentation

Welcome to the official documentation for **Verboisy**.

Verboisy is an autonomous web research and structured scrape-to-JSON agent. It combines the power of Playwright for robust web interaction with LLM-driven planning and extraction via LiteLLM.

## Features
- Autonomous DOM Navigation
- LLM-Driven Extraction and Typing (Pydantic v2)
- Built-in Browser Stealth
- Export to SQLite, JSON, CSV

## Quickstart

```bash
pip install verboisy
verboisy run --goal "Find YCombinator startups in AI from W24" --schema schema.json
