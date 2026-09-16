"""
Asynchronous SQLite connection pool and state management.
"""

import json
from typing import Any

import aiosqlite

from verboisy.utils.config import settings
from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """Manages SQLite connections and schema initialization for Verboisy."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.sqlite_db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Establish the database connection and run migrations."""
        if not self._conn:
            logger.debug("Connecting to database", path=self.db_path)
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._init_schema()

    async def _init_schema(self) -> None:
        """Initialize required database tables."""
        if not self._conn:
            return

        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                goal TEXT NOT NULL,
                schema_definition TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                url TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                action TEXT NOT NULL,
                parameters TEXT,
                url TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            """
        )
        await self._conn.commit()

    async def save_run(
        self, run_id: str, goal: str, schema_def: dict[str, Any], status: str
    ) -> None:
        """Save or update a run state."""
        if not self._conn:
            await self.connect()

        await self._conn.execute(  # type: ignore
            """
            INSERT INTO runs (run_id, goal, schema_definition, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET status=excluded.status
            """,
            (run_id, goal, json.dumps(schema_def), status),
        )
        await self._conn.commit()  # type: ignore

    async def save_extraction(self, run_id: str, url: str, data: dict[str, Any]) -> None:
        """Save a successfully extracted JSON payload."""
        if not self._conn:
            await self.connect()

        await self._conn.execute(  # type: ignore
            """
            INSERT INTO extractions (run_id, url, data)
            VALUES (?, ?, ?)
            """,
            (run_id, url, json.dumps(data)),
        )
        await self._conn.commit()  # type: ignore

    async def save_history_action(
        self, run_id: str, action: str, parameters: dict[str, Any], url: str
    ) -> None:
        """Save an action executed by the agent."""
        if not self._conn:
            await self.connect()

        await self._conn.execute(  # type: ignore
            """
            INSERT INTO history (run_id, action, parameters, url)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, action, json.dumps(parameters), url),
        )
        await self._conn.commit()  # type: ignore

    async def close(self) -> None:
        """Close the database connection safely."""
        if self._conn:
            logger.debug("Closing database connection")
            await self._conn.close()
            self._conn = None
