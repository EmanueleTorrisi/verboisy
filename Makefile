.PHONY: install test test-browser lint format build security docs validate clean

install:
	poetry install
	poetry run playwright install --with-deps chromium

test:
	poetry run pytest -m "not browser" --cov=src --cov-report=term-missing

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
