# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Core agent loop (plan → act → extract state machine).
- Playwright-based browser layer with stealth evasions.
- LiteLLM-backed planner supporting OpenAI, Anthropic, and Ollama.
- Pydantic schema builder for structured JSON extraction.
- SQLite storage backend with CSV/JSON export.
- Typer + Rich CLI.
