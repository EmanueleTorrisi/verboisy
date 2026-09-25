import json

import aiosqlite
import pytest
import verboisy.storage.sqlite as sqlite_module
from verboisy.storage.sqlite import DatabaseManager


async def fetch_rows(
    db_path,
    query: str,
    parameters: tuple = (),
) -> list[aiosqlite.Row]:
    async with aiosqlite.connect(db_path) as connection:
        connection.row_factory = aiosqlite.Row
        cursor = await connection.execute(query, parameters)
        return await cursor.fetchall()


def test_database_manager_uses_explicit_path(tmp_path) -> None:
    db_path = tmp_path / "explicit.db"

    manager = DatabaseManager(str(db_path))

    assert manager.db_path == str(db_path)
    assert manager._conn is None


def test_database_manager_uses_configured_default(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "default.db"
    monkeypatch.setattr(
        sqlite_module.settings,
        "sqlite_db_path",
        str(db_path),
    )

    manager = DatabaseManager()

    assert manager.db_path == str(db_path)


@pytest.mark.asyncio
async def test_init_schema_without_connection_returns(tmp_path) -> None:
    manager = DatabaseManager(str(tmp_path / "test.db"))

    await manager._init_schema()

    assert manager._conn is None


@pytest.mark.asyncio
async def test_connect_initializes_schema_and_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    manager = DatabaseManager(str(db_path))

    await manager.connect()
    first_connection = manager._conn

    assert first_connection is not None

    await manager.connect()

    assert manager._conn is first_connection

    rows = await fetch_rows(
        db_path,
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """,
    )

    table_names = {row["name"] for row in rows}

    assert {"runs", "extractions", "history"} <= table_names

    await manager.close()


@pytest.mark.asyncio
async def test_save_run_inserts_and_updates_existing_run(tmp_path) -> None:
    db_path = tmp_path / "runs.db"
    manager = DatabaseManager(str(db_path))

    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    await manager.save_run(
        "run-1",
        "find users",
        schema,
        "RUNNING",
    )

    await manager.save_run(
        "run-1",
        "find users",
        schema,
        "COMPLETED",
    )

    rows = await fetch_rows(
        db_path,
        """
        SELECT run_id, goal, schema_definition, status
        FROM runs
        WHERE run_id = ?
        """,
        ("run-1",),
    )

    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["goal"] == "find users"
    assert json.loads(rows[0]["schema_definition"]) == schema
    assert rows[0]["status"] == "COMPLETED"

    await manager.close()


@pytest.mark.asyncio
async def test_save_extraction_auto_connects_and_saves_data(tmp_path) -> None:
    db_path = tmp_path / "extractions.db"
    manager = DatabaseManager(str(db_path))

    await manager.save_run("run-1", "find users", {}, "RUNNING")
    data = {"name": "Alice", "age": 30}

    await manager.save_extraction(
        "run-1",
        "https://example.com",
        data,
    )

    await manager.save_extraction(
        "run-1",
        "https://example.org",
        {"name": "Bob"},
    )

    rows = await fetch_rows(
        db_path,
        """
        SELECT run_id, url, data
        FROM extractions
        ORDER BY id
        """,
    )

    assert len(rows) == 2
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["url"] == "https://example.com"
    assert json.loads(rows[0]["data"]) == data
    assert rows[1]["url"] == "https://example.org"

    await manager.close()


@pytest.mark.asyncio
async def test_save_history_action_auto_connects_and_saves_parameters(
    tmp_path,
) -> None:
    db_path = tmp_path / "history.db"
    manager = DatabaseManager(str(db_path))

    await manager.save_run("run-1", "find users", {}, "RUNNING")
    parameters = {"selector": "#login", "timeout": 5000}

    await manager.save_history_action(
        "run-1",
        "click",
        parameters,
        "https://example.com",
    )

    await manager.save_history_action(
        "run-1",
        "navigate",
        {"url": "https://example.org"},
        "https://example.org",
    )

    rows = await fetch_rows(
        db_path,
        """
        SELECT run_id, action, parameters, url
        FROM history
        ORDER BY id
        """,
    )

    assert len(rows) == 2
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["action"] == "click"
    assert json.loads(rows[0]["parameters"]) == parameters
    assert rows[0]["url"] == "https://example.com"
    assert rows[1]["action"] == "navigate"

    await manager.close()


@pytest.mark.asyncio
async def test_close_is_safe_when_called_multiple_times(tmp_path) -> None:
    db_path = tmp_path / "close.db"
    manager = DatabaseManager(str(db_path))

    await manager.connect()

    assert manager._conn is not None

    await manager.close()

    assert manager._conn is None

    await manager.close()

    assert manager._conn is None
