# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Implemented shared run/arun API and the documented run subcommand with resume.
- Added durable checkpoints, record deduplication, safe legacy migration and run locking.
- Corrected false completion on budget exhaustion and nonzero failure/export exits.
- Enforced JSON Schema constraints and explicit format dependencies without type coercion.
- Replaced blocking model calls with async requests, bounded retries and explicit key routing.
- Added URL policy, default browser sandboxing, resource cleanup and atomic exports.
- Reconciled examples, configuration, Docker environment and release gates.
- Updated pytest for GHSA-6w46-j5rx-g56g and expanded regression/integration checks.

### Acceptance still required
- Real Chromium/live-model demo and deployment validation; see docs/validation.md.


### Added
- Core agent loop (plan → act → extract state machine).
- Playwright-based browser layer with stealth evasions.
- LiteLLM-backed planner supporting OpenAI, Anthropic, and Ollama.
- Pydantic schema builder for structured JSON extraction.
- SQLite storage backend with CSV/JSON export.
- Typer + Rich CLI.
