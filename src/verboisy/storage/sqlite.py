"""Durable checkpoints and idempotent records, with additive legacy migration."""

import hashlib
import json
from pathlib import Path
from typing import Any

import aiosqlite
from filelock import FileLock, Timeout

from verboisy.core.state import ActionHistory, AgentState
from verboisy.utils.config import settings
from verboisy.utils.exceptions import ResumeError, VerboisyError


def record_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class DatabaseManager:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.sqlite_db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock: FileLock | None = None

    def acquire_run_lock(self) -> None:
        if self._lock is not None:
            return
        path = Path(self.db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path) + ".lock", timeout=0)
        try:
            lock.acquire()
        except Timeout:
            raise VerboisyError(f"Another run is active in database {self.db_path}") from None
        self._lock = lock

    async def connect(self) -> None:
        if self._conn is not None:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        try:
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.execute("PRAGMA busy_timeout=5000")
            await self._init_schema()
        except BaseException:
            await self.close()
            raise

    async def _init_schema(self) -> None:
        if self._conn is None:
            return
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL, goal TEXT NOT NULL,
                schema_definition TEXT NOT NULL, status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                url TEXT NOT NULL, data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                action TEXT NOT NULL, parameters TEXT, url TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
        """)
        # SQLite DDL is transactional only inside an explicit transaction. Keep
        # column creation and hash backfill atomic so interruption cannot leave
        # a partially migrated database that later appears up to date.
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            for table, column in (("runs", "state_json"), ("extractions", "record_hash")):
                async with self._conn.execute(f"PRAGMA table_info({table})") as cur:
                    columns = {row["name"] for row in await cur.fetchall()}
                if column not in columns:
                    await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                    if table == "extractions":
                        async with self._conn.execute(
                            "SELECT id, run_id, data FROM extractions ORDER BY id"
                        ) as cur:
                            rows = list(await cur.fetchall())
                        seen = set()
                        for row in rows:
                            digest = record_hash(json.loads(row["data"]))
                            key = (row["run_id"], digest)
                            if key not in seen:
                                await self._conn.execute(
                                    "UPDATE extractions SET record_hash=? WHERE id=?",
                                    (digest, row["id"]),
                                )
                                seen.add(key)
                            # Preserve legacy duplicate rows without assigning duplicate hashes.
            for query in (
                "CREATE UNIQUE INDEX IF NOT EXISTS extraction_dedup "
                "ON extractions(run_id, record_hash) WHERE record_hash IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS history_run ON history(run_id, id)",
                "CREATE INDEX IF NOT EXISTS extraction_run ON extractions(run_id, id)",
            ):
                await self._conn.execute(query)
            await self._conn.commit()
        except BaseException:
            await self._conn.rollback()
            raise

    async def _connection(self) -> aiosqlite.Connection:
        await self.connect()
        assert self._conn is not None
        return self._conn

    async def save_run(
        self, run_id: str, goal: str, schema_def: dict[str, Any], status: str
    ) -> None:
        conn = await self._connection()
        await conn.execute(
            """
            INSERT INTO runs (run_id, goal, schema_definition, status) VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                completed_at=CASE WHEN excluded.status='COMPLETED'
                    THEN CURRENT_TIMESTAMP ELSE NULL END
        """,
            (run_id, goal, json.dumps(schema_def, allow_nan=False), status),
        )
        await conn.commit()

    async def checkpoint(self, state: AgentState, action: ActionHistory | None = None) -> None:
        conn = await self._connection()
        payload = state.model_dump_json(exclude={"history", "extracted_data"})
        try:
            await conn.execute(
                """
                INSERT INTO runs (run_id, goal, schema_definition, status, state_json, completed_at)
                VALUES (?, ?, ?, ?, ?, CASE WHEN ?='COMPLETED' THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                    state_json=excluded.state_json, completed_at=excluded.completed_at
            """,
                (
                    state.run_id,
                    state.goal,
                    json.dumps(state.target_schema),
                    state.status,
                    payload,
                    state.status,
                ),
            )
            if action is not None:
                await conn.execute(
                    "INSERT INTO history (run_id, action, parameters, url) VALUES (?, ?, ?, ?)",
                    (state.run_id, action.action, json.dumps(action.parameters), action.url),
                )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise

    async def save_extraction(self, run_id: str, url: str, data: dict[str, Any]) -> bool:
        conn = await self._connection()
        async with conn.execute(
            """
            INSERT INTO extractions (run_id, url, data, record_hash) VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id, record_hash) WHERE record_hash IS NOT NULL DO NOTHING
        """,
            (run_id, url, json.dumps(data, ensure_ascii=False, allow_nan=False), record_hash(data)),
        ) as cur:
            inserted = cur.rowcount == 1
        await conn.commit()
        return inserted

    async def save_history_action(
        self, run_id: str, action: str, parameters: dict[str, Any], url: str
    ) -> None:
        conn = await self._connection()
        await conn.execute(
            "INSERT INTO history (run_id, action, parameters, url) VALUES (?, ?, ?, ?)",
            (run_id, action, json.dumps(parameters), url),
        )
        await conn.commit()

    async def records(self, run_id: str) -> list[dict[str, Any]]:
        conn = await self._connection()
        async with conn.execute(
            "SELECT data FROM extractions WHERE run_id=? ORDER BY id", (run_id,)
        ) as cur:
            return [json.loads(row["data"]) for row in await cur.fetchall()]

    async def load_run(self, run_id: str | None = None) -> AgentState:
        conn = await self._connection()
        if run_id is None:
            query = "SELECT * FROM runs WHERE UPPER(status) != 'COMPLETED' ORDER BY id DESC LIMIT 1"
            params: tuple[str, ...] = ()
        else:
            query = "SELECT * FROM runs WHERE substr(run_id,1,length(?))=? ORDER BY id DESC"
            params = (run_id, run_id)
        async with conn.execute(query, params) as cur:
            rows = list(await cur.fetchall())
        if not rows:
            raise ResumeError(
                f"No matching {'incomplete ' if run_id is None else ''}run in {self.db_path}"
            )
        exact = [row for row in rows if row["run_id"] == run_id]
        if len(rows) > 1 and not exact:
            raise ResumeError(f"Ambiguous run id in {self.db_path}; use the full id")
        row = exact[0] if exact else rows[0]
        state = (
            AgentState.model_validate_json(row["state_json"])
            if row["state_json"]
            else AgentState(
                run_id=row["run_id"],
                goal=row["goal"],
                target_schema=json.loads(row["schema_definition"]),
                status=row["status"].upper(),
            )
        )
        state.extracted_data = await self.records(state.run_id)
        async with conn.execute(
            "SELECT * FROM history WHERE run_id=? ORDER BY id", (state.run_id,)
        ) as cur:
            state.history = [
                ActionHistory(
                    action=h["action"],
                    parameters=json.loads(h["parameters"] or "{}"),
                    url=h["url"],
                    **({"timestamp": h["timestamp"]} if h["timestamp"] else {}),
                )
                for h in await cur.fetchall()
            ]
        return state

    async def close(self) -> None:
        try:
            if self._conn is not None:
                conn, self._conn = self._conn, None
                await conn.close()
        finally:
            if self._lock is not None:
                self._lock.release()
                self._lock = None
