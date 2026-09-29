.PHONY: install test test-browser lint format build security docs validate clean

install:
	poetry install
	poetry run verboisy setup

test:
	poetry run pytest -m "not browser and not live" --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100

test-browser:
	VERBOISY_REQUIRE_BROWSER=1 poetry run pytest -m browser -v

lint:
	poetry run ruff check .
	poetry run ruff format --check .
	poetry run mypy src

format:
	poetry run ruff check --fix .
	poetry run ruff format .

build:
	poetry build

security:
	poetry run pip-audit --local

docs:
	poetry run mkdocs build --strict

validate: lint test test-browser security docs build

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache htmlcov dist build site
