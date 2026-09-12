.PHONY: install test lint format clean

install:
	poetry install
	poetry run playwright install --with-deps chromium

test:
	poetry run pytest tests/ -v

lint:
	poetry run ruff check .
	poetry run mypy src/

format:
	poetry run ruff check --fix .
	poetry run ruff format .

clean:
	rm -rf .mypy_cache .pytest_cache
	rm -rf dist/
	rm -rf build/
	find . -type d -name __pycache__ -exec rm -rf {} +
