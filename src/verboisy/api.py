"""Shared public Python and CLI execution API."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verboisy.core.agent import Agent
from verboisy.core.state import AgentState
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.storage.exporters import DataExporter
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError


@dataclass(frozen=True)
class RunResult:
    run_id: str
    records: list[dict[str, Any]]
    export_path: Path | None
    db_path: Path
    completed: bool
    status: str
    stop_reason: str | None


def _schema(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return SchemaBuilder.normalize(value)
    try:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerboisyError(f"Cannot load schema {value} ({type(exc).__name__})") from None
    return SchemaBuilder.normalize(payload)


def _export_path(value: str | Path | None, db_path: str) -> Path | None:
    if value is None:
        return None
    path = Path(value).resolve()
    if path.suffix.lower() not in (".json", ".csv"):
        raise VerboisyError("Export path must end in .json or .csv")
    if path == Path(db_path).resolve():
        raise VerboisyError("Export path must differ from the database path")
    return path


async def arun(
    *,
    goal: str | None = None,
    schema: str | Path | dict[str, Any] | None = None,
    export: str | Path | None = None,
    resume: bool | str = False,
    headless: bool | None = None,
    max_steps: int | None = None,
    config: Settings | None = None,
) -> RunResult:
    """Run asynchronously; budgets renew on resume while cumulative progress is retained."""
    config = (config or Settings()).model_copy()
    if headless is not None:
        config.headless_browser = headless
    steps = max_steps if max_steps is not None else config.max_steps
    if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
        raise VerboisyError("max_steps must be a positive integer")
    if not isinstance(resume, bool | str) or (isinstance(resume, str) and not resume):
        raise VerboisyError("resume must be True, False, or a nonempty run id")
    destination = _export_path(export, config.sqlite_db_path)
    db = DatabaseManager(config.sqlite_db_path)
    try:
        db.acquire_run_lock()
        if resume:
            state = await db.load_run(resume if isinstance(resume, str) else None)
            state.target_schema = SchemaBuilder.normalize(state.target_schema)
            if destination is None:
                destination = _export_path(state.export_path, config.sqlite_db_path)
        else:
            if not goal or not goal.strip() or schema is None:
                raise VerboisyError("New runs require goal and schema")
            state = AgentState(goal=goal, target_schema=_schema(schema), max_steps=steps)
        state.export_path = str(destination) if destination is not None else None
        if state.status != "COMPLETED":
            agent = Agent(state.goal, state.target_schema, steps, config=config, state=state, db=db)
            state = await agent.run()
        else:
            # A completed run may be re-exported without browser/model access.
            from verboisy.extractor.engine import ExtractionEngine

            ExtractionEngine(state.target_schema, config=config).validate_collection(
                state.extracted_data
            )
            await db.checkpoint(state)
        written = None
        if state.status == "COMPLETED" and destination is not None:
            try:
                if destination.suffix.lower() == ".csv":
                    DataExporter.export_csv(state.extracted_data, destination)
                else:
                    DataExporter.export_json(state.extracted_data, destination)
                written = destination
            except (OSError, ValueError) as exc:
                raise VerboisyError(
                    f"Export failed ({type(exc).__name__}); run {state.run_id} is saved. "
                    "Resume that id with a writable export path to retry."
                ) from None
        return RunResult(
            state.run_id,
            state.extracted_data,
            written,
            Path(config.sqlite_db_path).resolve(),
            state.status == "COMPLETED",
            state.status,
            state.stop_reason,
        )
    finally:
        await db.close()


def run(
    *,
    goal: str | None = None,
    schema: str | Path | dict[str, Any] | None = None,
    export: str | Path | None = None,
    resume: bool | str = False,
    headless: bool | None = None,
    max_steps: int | None = None,
    config: Settings | None = None,
) -> RunResult:
    """Synchronous entry point. In notebooks or an event loop, await arun()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            arun(
                goal=goal,
                schema=schema,
                export=export,
                resume=resume,
                headless=headless,
                max_steps=max_steps,
                config=config,
            )
        )
    raise VerboisyError("run() cannot execute inside an event loop; use await arun(...)")
