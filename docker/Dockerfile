
FROM python:3.11-slim

# Python and Playwright environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# Install Poetry and create application virtual environment
RUN python -m pip install --no-cache-dir poetry==2.5.1 \
    && python -m venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy dependency metadata first to improve layer caching
COPY pyproject.toml poetry.lock README.md LICENSE ./

# Copy application source
COPY src ./src

# Install production dependencies and Chromium
# Including OS dependencies while still running as root
RUN poetry install --only main \
    && python -m playwright install --with-deps chromium

# Copy examples and entrypoint
COPY examples ./examples
COPY docker/entrypoint.sh /entrypoint.sh

# Create non-root application user and persistent data directory
RUN chmod +x /entrypoint.sh \
    && useradd --create-home --uid 10001 verboisy \
    && mkdir -p /data \
    && chown verboisy:verboisy /data

# SQLite database location
ENV SQLITE_DB_PATH=/data/verboisy.db

# Run Verboisy without root privileges
USER verboisy

# Application entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["verboisy", "--help"]
