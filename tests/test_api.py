"""Public API validation, restoration, and export failures."""

import json

import pytest
from verboisy import RunResult, arun, run
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.exceptions import VerboisyError

from tests.conftest import action
from tests.test_core.test_agent import SCHEMA


async def test_sync_api_rejects_running_loop():
    with pytest.raises(VerboisyError, match="await arun"):
        run(goal="x", schema={})


def test_public_sync_api(config, fake_browser, model_script, tmp_path):
    model_script(action("FINISH"))
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA))
    result = run(goal="Find names", schema=path, config=config)
    assert isinstance(result, RunResult) and result.completed


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"goal": " ", "schema": {}},
        {"goal": "x"},
        {"goal": "x", "schema": {}, "max_steps": 0},
        {"resume": ""},
        {"resume": 3},
        {"goal": "x", "schema": {}, "export": "result.txt"},
        {"goal": "x", "schema": "missing-schema.json"},
    ],
)
async def test_invalid_inputs(kwargs, config):
    with pytest.raises(VerboisyError):
        await arun(config=config, **kwargs)


async def test_no_run_names_database(config):
    with pytest.raises(VerboisyError, match="runs.db"):
        await arun(resume=True, config=config)


async def test_export_failure_can_retry_without_model(config, fake_browser, model_script, tmp_path):
    directory = tmp_path / "result.json"
    directory.mkdir()
    model_script(action("EXTRACT"), {"results": [{"name": "Alice"}]}, action("FINISH"))
    with pytest.raises(VerboisyError, match="Export failed"):
        await arun(goal="Find names", schema=SCHEMA, export=directory, config=config)
    db = DatabaseManager(config.sqlite_db_path)
    conn = await db._connection()
    async with conn.execute("SELECT run_id FROM runs") as cur:
        run_id = (await cur.fetchone())["run_id"]
    await db.close()
    mock = model_script()
    result = await arun(resume=run_id, export=tmp_path / "retry.json", config=config)
    assert json.loads(result.export_path.read_text()) == [{"name": "Alice"}]
    mock.assert_not_awaited()


async def test_empty_export_written(config, fake_browser, model_script, tmp_path):
    model_script(action("FINISH"))
    output = tmp_path / "empty.json"
    await arun(goal="Find nothing", schema=SCHEMA, export=output, config=config)
    assert json.loads(output.read_text()) == []


async def test_database_export_collision(config):
    config.sqlite_db_path = config.sqlite_db_path + ".json"
    with pytest.raises(VerboisyError, match="differ"):
        await arun(goal="x", schema={}, export=config.sqlite_db_path, config=config)


async def test_explicit_headless_and_csv_export(config, fake_browser, model_script, tmp_path):
    """Honor the headless override and export completed records as CSV."""
    model_script(
        action("EXTRACT"),
        {"results": [{"name": "Alice"}]},
        action("FINISH"),
    )

    output = tmp_path / "results.csv"

    result = await arun(
        goal="Find names",
        schema=SCHEMA,
        export=output,
        headless=False,
        config=config,
    )

    assert result.completed
    assert result.export_path == output.resolve()
    assert result.records == [{"name": "Alice"}]

    assert output.exists()
    assert "Alice" in output.read_text(encoding="utf-8")
