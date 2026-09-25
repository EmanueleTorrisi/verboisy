FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

RUN python -m pip install --no-cache-dir poetry==2.5.1 \
    && python -m venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY src ./src
RUN poetry install --only main \
    && python -m playwright install --with-deps chromium
COPY examples ./examples
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && useradd --create-home --uid 10001 verboisy \
    && mkdir -p /data \
    && chown verboisy:verboisy /data

ENV SQLITE_DB_PATH=/data/verboisy.db
USER verboisy
ENTRYPOINT ["/entrypoint.sh"]
CMD ["verboisy", "--help"]
