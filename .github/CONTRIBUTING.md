# Contributing to Verboisy

Thank you for your interest in contributing to Verboisy.

Contributions of all kinds are welcome, including bug reports, feature suggestions, documentation improvements, tests, and code changes.

Please take a moment to read this guide before opening an issue or pull request.

## Before You Start

Please search the existing issues and pull requests before creating a new one. Your problem or idea may already have been discussed.

For bugs, please use the **Bug Report** issue form.

For new ideas or improvements, please use the **Feature Request** issue form.

For questions and general discussion, please use **GitHub Discussions**.

Security vulnerabilities must **not** be reported publicly. Please follow the instructions in [SECURITY.md](SECURITY.md).

## Development Setup

Clone the repository:

```bash
git clone https://github.com/EmanueleTorrisi/verboisy.git
cd verboisy
```

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Linux and macOS

```bash
source .venv/bin/activate
```

Windows

```powershell
.venv\Scripts\activate
```

Install the project and development dependencies:

```bash
poetry install
```
If the development dependency configuration differs from the command above, follow the instructions provided in [README.md](../README.md) or [pyproject.toml](../pyproject.toml).

# Making Changes

Before submitting a change:

-> Keep changes focused and minimal.

-> Follow the existing project structure and coding conventions.

-> Add or update tests when changing behavior.

-> Update documentation when necessary.

-> Avoid unrelated formatting or refactoring changes.

# Testing

Run the project's test suite before opening a pull request.
For example:

```bash
poetry run pytest
```

Also make sure the project can be installed and imported successfully in a clean environment.

If Verboisy has additional checks such as linters, formatters, or type checking, run those checks as well.

# Pull Requests

Pull requests should:

-> Clearly explain what was changed and why.

-> Reference relevant issues when applicable.

-> Include tests for new or changed behavior.

-> Keep the scope focused.

-> Avoid introducing breaking changes without prior discussion.

A useful pull request description should explain:

**What changed?**

Describe the implementation.

**Why was it changed?**

Explain the problem or motivation.

**How was it tested?**

Describe the tests and checks that were performed.

# Commit Messages

Use clear and descriptive commit messages.

Examples:

```bash
fix: handle empty transcription input
```

```bash
feat: add configurable transcription timeout
```

```bash
docs: improve installation instructions
```

Keep commits focused so that they are easy to review.

# Code Style

Follow the conventions already established in the repository.

Do not introduce a new style or formatting system without a good reason.

When automated formatting or linting tools are configured, use them before submitting a pull request.

# Reporting Bugs

A good bug report should include:

-> A clear description of the problem

-> Steps to reproduce it

-> Expected behavior

-> Actual behavior

-> Error output or logs

-> Environment information

-> A minimal reproducible example when possible

**Please remove credentials, API keys, tokens, and other sensitive information from reports.**

# Suggesting Features

Feature requests should explain:

-> The problem you are trying to solve

-> The proposed behavior

-> Why the feature would be useful

-> Any alternatives or workarounds you have considered

# Community Standards

Please be respectful and constructive when communicating with maintainers and contributors.

By participating in this project, you agree to follow the project's Code of Conduct.

# Questions

For general questions, ideas, and community discussion, please use GitHub Discussions rather than opening an issue.

*Thank you for contributing to Verboisy.*
