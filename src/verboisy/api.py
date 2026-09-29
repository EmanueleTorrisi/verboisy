"""Public evidence-backed research API. Unknown completion remains explicit."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from verboisy import __version__
from verboisy.core.research import ResearchRunner
from verboisy.core.search import brave_search
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.extractor.evidenced import PROPOSE, REVIEW
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.storage.dataset import export_dataset
from verboisy.storage.research import ResearchStore
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
    manifest_path: Path | None = None


def _json(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise VerboisyError("Cannot load JSON configuration file") from None
    if not isinstance(payload, dict):
        raise VerboisyError("Configuration must be a JSON object")
    return payload


def _schema(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    return SchemaBuilder.normalize(_json(value))


def _export_path(value: str | Path | None, db_path: str) -> Path | None:
    if value is None:
        return None
    path = Path(value).resolve()
    if path.suffix.lower() not in (".json", ".csv"):
        raise VerboisyError("Export path must end in .json or .csv")
    protected = {Path(db_path + s).resolve() for s in ("", "-wal", "-shm", ".lock")}
    outputs = {
        path,
        path.with_suffix(path.suffix + ".manifest.json"),
        path.with_suffix(path.suffix + ".evidence.json"),
    }
    if outputs & protected:
        raise VerboisyError("Export files must differ from database paths")
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
    task: TaskSpec | dict[str, Any] | str | Path | None = None,
) -> RunResult:
    """Start/resume research. max_steps limits page visits for this invocation.

    Task and request budgets are cumulative. Only an explicit accepted-record target
    produces COMPLETED; an exhausted observed crawl remains EXHAUSTED for review.
    """
    config = (config or Settings()).model_copy()
    if headless is not None:
        config.headless_browser = headless
    steps = max_steps if max_steps is not None else config.max_steps
    if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
        raise VerboisyError("max_steps must be a positive integer")
    if not isinstance(resume, bool | str) or isinstance(resume, str) and not resume:
        raise VerboisyError("resume must be True, False, or a nonempty run id")
    destination = _export_path(export, config.sqlite_db_path)
    if resume and (goal is not None or schema is not None or task is not None):
        raise VerboisyError(
            "Resume uses its saved goal/schema/task; start a new run to change them"
        )
    if not resume and (not goal or not goal.strip() or schema is None):
        raise VerboisyError("New runs require goal and schema")
    if destination:
        outputs = {
            destination,
            destination.with_suffix(destination.suffix + ".manifest.json"),
            destination.with_suffix(destination.suffix + ".evidence.json"),
        }
        if outputs & {Path(v).resolve() for v in (schema, task) if isinstance(v, str | Path)}:
            raise VerboisyError("Export files must differ from schema/task inputs")
    spec: TaskSpec
    target_schema: dict[str, Any]
    if not resume:
        try:
            spec = (
                task
                if isinstance(task, TaskSpec)
                else TaskSpec.model_validate(_json(task) if task is not None else {})
            )
        except ValidationError:
            raise VerboisyError("Invalid task specification") from None
        target_schema = _schema(schema)  # type: ignore[arg-type]
        if not spec.seed_urls:
            seeds = re.findall(r'https?://[^\s<>"\']+', goal or "")
            spec = spec.model_copy(update={"seed_urls": [s.rstrip(".,;)") for s in seeds]})
        if not spec.seed_urls:
            if config.search_provider != "brave":
                raise VerboisyError(
                    "Provide seed URLs in --task or goal, or configure Brave Search"
                )
            leads = await brave_search(goal or "", config)
            spec = spec.model_copy(update={"seed_urls": [r.url for r in leads.results]})
        seeds = [canonical_url(u) for u in spec.seed_urls]
        if not seeds or any(u is None for u in seeds):
            raise VerboisyError("At least one valid HTTP(S) seed URL is required")
        spec = spec.model_copy(update={"seed_urls": list(dict.fromkeys(seeds))})
        if (
            spec.target_records
            and target_schema["type"] == "array"
            and not target_schema.get("minItems", 0)
            <= spec.target_records
            <= target_schema.get("maxItems", 100000)
        ):
            raise VerboisyError("Target conflicts with schema collection limits")
    store = ResearchStore(config.sqlite_db_path)
    try:
        if resume:
            state = store.load(resume if isinstance(resume, str) else None)
            rid = state["id"]
            spec = TaskSpec.model_validate_json(state["task_json"])
            target_schema = json.loads(state["schema_json"])
            destination = destination or _export_path(state["export_path"], config.sqlite_db_path)
        else:
            rid = store.create(
                goal or "", target_schema, spec, str(destination) if destination else None
            )
            for url in spec.seed_urls:
                store.queue(rid, url, 0, None)
            state = store.load(rid)
        if state["status"] != "COMPLETED":
            store.event(
                rid,
                "run_config",
                {
                    "software_version": __version__,
                    "model": config.litellm_model,
                    "prompt_sha256": hashlib.sha256((PROPOSE + REVIEW).encode()).hexdigest(),
                    "max_output_tokens": config.max_tokens,
                    "request_budget": config.model_request_budget or config.max_total_tokens,
                },
            )
            runner = ResearchRunner(store, rid, config)
            await runner.run(steps)
        state = store.load(rid)
        manifest = None
        if destination:
            try:
                manifest = export_dataset(store, rid, destination, target_schema, spec)
            except (OSError, ValueError):
                raise VerboisyError(
                    f"Export failed; run {rid} is saved. Resume with a writable destination"
                ) from None
        return RunResult(
            rid,
            store.records(rid),
            destination,
            store.path,
            state["status"] == "COMPLETED",
            state["status"],
            state["reason"],
            manifest,
        )
    finally:
        store.close()


def run(**kwargs: Any) -> RunResult:
    """Synchronous wrapper; notebooks should await arun()."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(arun(**kwargs))
    raise VerboisyError("run() cannot execute inside an event loop; use await arun(...)")
