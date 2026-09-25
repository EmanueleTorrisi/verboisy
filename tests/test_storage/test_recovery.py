"""Real on-disk migration, deduplication, and concurrent-writer regressions."""

import json
import sqlite3

import pytest
from verboisy.core.state import ActionHistory, AgentState
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.exceptions import ResumeError, VerboisyError


async def test_dedup_survives_reopen(config):
    first = DatabaseManager(config.sqlite_db_path)
    await first.save_run("one", "goal", {}, "RUNNING")
    assert await first.save_extraction("one", "https://example.com", {"b": 2, "a": 1})
    await first.close()
    second = DatabaseManager(config.sqlite_db_path)
    assert not await second.save_extraction("one", "https://other.com", {"a": 1, "b": 2})
    assert len(await second.records("one")) == 1
    await second.close()


async def test_checkpoint_and_history_roundtrip(test_db):
    state = AgentState(
        goal="goal",
        target_schema={},
        current_url="https://example.com/?page=2",
        step_count=7,
        status="PAUSED",
        export_path="/saved/result.json",
        token_count=42,
    )
    action = ActionHistory(action="CLICK", parameters={"selector": "#next"}, url=state.current_url)
    await test_db.checkpoint(state, action)
    loaded = await test_db.load_run()
    assert loaded.current_url == state.current_url
    assert loaded.step_count == 7 and loaded.token_count == 42
    assert loaded.export_path == state.export_path
    assert loaded.history[0].action == "CLICK"


async def test_concurrent_run_rejected_and_lock_released(config):
    first = DatabaseManager(config.sqlite_db_path)
    second = DatabaseManager(config.sqlite_db_path)
    first.acquire_run_lock()
    with pytest.raises(VerboisyError, match="Another run"):
        second.acquire_run_lock()
    await first.close()
    second.acquire_run_lock()
    await second.close()


async def test_prefix_resolution_and_completed_selection(test_db):
    await test_db.save_run("abc-one", "one", {}, "PAUSED")
    await test_db.save_run("abc-two", "two", {}, "COMPLETED")
    assert (await test_db.load_run()).run_id == "abc-one"
    assert (await test_db.load_run("abc-two")).status == "COMPLETED"
    with pytest.raises(ResumeError, match="Ambiguous"):
        await test_db.load_run("abc-")
    with pytest.raises(ResumeError):
        await test_db.load_run("' OR 1=1 --")


async def test_orphan_insert_rejected(test_db):
    with pytest.raises(sqlite3.IntegrityError):
        await test_db.save_extraction("missing", "https://example.com", {"name": "Alice"})


async def test_legacy_migration_preserves_data(config):
    with sqlite3.connect(config.sqlite_db_path) as conn:
        conn.executescript("""
            CREATE TABLE runs (id INTEGER PRIMARY KEY, run_id TEXT UNIQUE, goal TEXT,
              schema_definition TEXT, status TEXT, created_at TIMESTAMP, completed_at TIMESTAMP);
            CREATE TABLE extractions (id INTEGER PRIMARY KEY, run_id TEXT, url TEXT, data TEXT,
              created_at TIMESTAMP);
            CREATE TABLE history (id INTEGER PRIMARY KEY, run_id TEXT, action TEXT, parameters TEXT,
              url TEXT, timestamp TIMESTAMP);
        """)
        conn.execute("INSERT INTO runs VALUES (1,'legacy','goal','{}','RUNNING',NULL,NULL)")
        for index in (1, 2):
            conn.execute(
                "INSERT INTO extractions VALUES (?,'legacy','https://example.com',?,NULL)",
                (index, json.dumps({"name": "Alice"})),
            )
    manager = DatabaseManager(config.sqlite_db_path)
    state = await manager.load_run("legacy")
    assert state.extracted_data == [{"name": "Alice"}, {"name": "Alice"}]
    assert not await manager.save_extraction("legacy", "https://example.com", {"name": "Alice"})
    await manager.close()
    with sqlite3.connect(config.sqlite_db_path) as conn:
        assert conn.execute("SELECT count(*) FROM extractions").fetchone()[0] == 2


async def test_legacy_migration_failure_rolls_back_columns(config):
    with sqlite3.connect(config.sqlite_db_path) as connection:
        connection.executescript("""
            CREATE TABLE runs (id INTEGER PRIMARY KEY, run_id TEXT UNIQUE, goal TEXT,
              schema_definition TEXT, status TEXT, created_at TIMESTAMP, completed_at TIMESTAMP);
            CREATE TABLE extractions (id INTEGER PRIMARY KEY, run_id TEXT, url TEXT, data TEXT,
              created_at TIMESTAMP);
            CREATE TABLE history (id INTEGER PRIMARY KEY, run_id TEXT, action TEXT, parameters TEXT,
              url TEXT, timestamp TIMESTAMP);
            INSERT INTO runs VALUES (1,'legacy','goal','{}','RUNNING',NULL,NULL);
            INSERT INTO extractions VALUES (1,'legacy','https://example.com','{}',NULL);
            INSERT INTO extractions VALUES (2,'legacy','https://example.com','broken-json',NULL);
        """)
    manager = DatabaseManager(config.sqlite_db_path)
    with pytest.raises(json.JSONDecodeError):
        await manager.connect()
    assert manager._conn is None
    with sqlite3.connect(config.sqlite_db_path) as connection:
        assert "state_json" not in {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        assert "record_hash" not in {
            row[1] for row in connection.execute("PRAGMA table_info(extractions)")
        }
        assert connection.execute("SELECT count(*) FROM extractions").fetchone()[0] == 2


def test_process_death_preserves_commits_and_releases_lock(config):
    import os
    import subprocess
    import sys

    script = """
import asyncio, os
from verboisy.storage.sqlite import DatabaseManager
async def main():
    db = DatabaseManager(os.environ["VERBOISY_CRASH_TEST_DB"])
    db.acquire_run_lock()
    await db.save_run("crash", "fixture", {}, "RUNNING")
    await db.save_extraction("crash", "https://example.com", {"saved": True})
    conn = await db._connection()
    await conn.execute("INSERT INTO extractions (run_id,url,data) VALUES (?,?,?)",
                       ("crash", "https://example.com", '{"uncommitted":true}'))
    os._exit(77)
asyncio.run(main())
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "VERBOISY_CRASH_TEST_DB": config.sqlite_db_path},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 77, completed.stderr
    with sqlite3.connect(config.sqlite_db_path) as connection:
        rows = connection.execute("SELECT data FROM extractions").fetchall()
    assert [json.loads(row[0]) for row in rows] == [{"saved": True}]
    from filelock import FileLock

    with FileLock(config.sqlite_db_path + ".lock", timeout=0):
        pass


async def test_checkpoint_failure_rolls_back_insert(test_db):
    """A failed checkpoint must not leave a partially inserted run."""
    conn = await test_db._connection()

    await conn.execute("DROP TABLE history")
    await conn.commit()

    state = AgentState(
        goal="Find names",
        target_schema={},
    )

    action = ActionHistory(
        action="CLICK",
        parameters={"selector": "#next"},
        url="https://example.com",
    )

    with pytest.raises(
        sqlite3.OperationalError,
        match="no such table",
    ):
        await test_db.checkpoint(state, action)

    async with conn.execute(
        "SELECT COUNT(*) FROM runs WHERE run_id = ?",
        (state.run_id,),
    ) as cursor:
        row = await cursor.fetchone()

    assert row[0] == 0
