# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Public evidence-backed research API for the simplified Verboisy product."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from verboisy import __version__
from verboisy.core.fitness import scalar_field_schemas
from verboisy.core.initial_discovery import (
    discover_seed_sources,
    preflight_initial_discovery,
    publish_initial_discovery,
)
from verboisy.core.planner import (
    ResearchPlan,
    build_research_plan,
)
from verboisy.core.research import ResearchRunner
from verboisy.core.search import web_search
from verboisy.evidence.models import ProjectionPlan, TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.extractor.evidenced import PROPOSE, REVIEW
from verboisy.extractor.ingestion import run_dataset_sources, validate_dataset_evidence
from verboisy.extractor.range_changes import offer_saved_range_change, saved_range_evidence
from verboisy.extractor.schema_builder import SchemaBuilder
from verboisy.llm.client import LLMClient
from verboisy.output import prepare_output, write_output
from verboisy.presentation_config import preferences, resolve_saved_preferences
from verboisy.product import (
    SortKey,
    SourcePolicy,
    parse_simple_schema,
)
from verboisy.storage.changes import SavedChange, decide_change, pending_change
from verboisy.storage.path_safety import (
    dataset_output_paths,
    export_input_paths,
    local_source_paths,
    validate_output_paths,
)
from verboisy.storage.product_options import saved_export_destinations, saved_product_options
from verboisy.storage.research import ResearchStore
from verboisy.time_series import validate_time_series
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import (
    VerboisyError,
)


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
    export_paths: tuple[Path, ...] = ()
    manifest_paths: tuple[Path, ...] = ()
    proof_path: Path | None = None
    notices: tuple[str, ...] = ()
    inferred_schema: dict[str, Any] | None = None
    dataset_consistency: dict[str, Any] | None = None


def _proposal_pause_result(store: ResearchStore, rid: str, change: SavedChange) -> RunResult:
    return RunResult(
        run_id=rid,
        records=[],
        export_path=None,
        db_path=store.path,
        completed=False,
        status="PAUSED",
        stop_reason="proposed_changes",
        notices=(
            "* " + change.request.description,
            f"* Keep existing requirements: verboisy run --resume {rid}",
            f"* Accept these changes: verboisy run --okresume {rid}",
            f"* Inspect the exact proposal: verboisy changes --run-id {rid}",
        ),
    )


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


def _schema(
    value: str | Path | dict[str, Any] | list[str] | tuple[str, ...], *, strings: bool = False
) -> tuple[dict[str, Any], bool]:
    if isinstance(value, dict):
        if strings:
            raise VerboisyError(
                "--strings applies to simple column schemas, not explicit JSON Schema"
            )
        return SchemaBuilder.normalize(value), False
    if isinstance(value, list | tuple):
        return SchemaBuilder.normalize(parse_simple_schema(value, strings=strings)), True
    if isinstance(value, Path):
        if strings:
            raise VerboisyError(
                "--strings applies to simple column schemas, not explicit JSON Schema"
            )
        return SchemaBuilder.normalize(_json(value)), False
    text = value.strip()
    if text.startswith("["):
        return SchemaBuilder.normalize(parse_simple_schema(text, strings=strings)), True
    if strings:
        raise VerboisyError("--strings applies to simple column schemas, not explicit JSON Schema")
    return SchemaBuilder.normalize(_json(text)), False


def _export_paths(
    value: str | Path | Sequence[str | Path] | None, db_path: str
) -> tuple[Path, ...]:
    if value is None:
        return ()
    values = [value] if isinstance(value, str | Path) else list(value)
    result: list[Path] = []
    protected = {Path(db_path + suffix).resolve() for suffix in ("", "-wal", "-shm", ".lock")}
    occupied: set[Path] = set()
    for raw in values:
        if Path(raw).is_symlink():
            raise VerboisyError("Export destination cannot be a symlink")
        path = Path(raw).resolve()
        if path.suffix.lower() not in (".json", ".csv"):
            raise VerboisyError("Export paths must end in .json or .csv")
        outputs = {
            path,
            path.with_suffix(path.suffix + ".manifest.json"),
            path.with_suffix(path.suffix + ".evidence.json"),
            path.with_suffix(path.suffix + ".events.json"),
            path.with_suffix(path.suffix + ".assets.json"),
            path.with_name(path.stem + ".proof.txt"),
        }
        if outputs & protected:
            raise VerboisyError("Export files must differ from database paths")
        if path in result:
            raise VerboisyError(f"Duplicate export destination: {path}")
        distinct_outputs = outputs - {path.with_name(path.stem + ".proof.txt")}
        if distinct_outputs & occupied:
            raise VerboisyError("Export destinations have overlapping output files")
        occupied.update(distinct_outputs)
        result.append(path)
    try:
        validate_output_paths(
            {output for path in result for output in dataset_output_paths(path)},
            (Path(db_path + suffix) for suffix in ("", "-wal", "-shm", ".lock")),
        )
    except (OSError, ValueError) as error:
        raise VerboisyError("Export failed: " + str(error)) from None
    return tuple(result)


def _protect_exports(destinations: tuple[Path, ...], inputs: set[Path]) -> None:
    """Validate the full bundle before run creation or any resume decision."""
    try:
        validate_output_paths(
            {path for destination in destinations for path in dataset_output_paths(destination)},
            inputs,
        )
    except (OSError, ValueError) as error:
        raise VerboisyError(str(error)) from None


def _export_path(value: str | Path | None, db_path: str) -> Path | None:
    """Backward-compatible single-destination validator."""

    paths = _export_paths(value, db_path)
    return paths[0] if paths else None


def _schema_fields(schema: dict[str, Any]) -> list[str]:
    item = schema["items"] if schema["type"] == "array" else schema
    return list(item.get("properties", {}))


def _normalize_sort_keys(
    order: Sequence[SortKey | tuple[str, str] | dict[str, str]] | None,
) -> list[SortKey]:
    result: list[SortKey] = []
    for item in order or []:
        if isinstance(item, SortKey):
            result.append(item)
        elif isinstance(item, tuple) and len(item) == 2:
            result.append(SortKey(str(item[0]), str(item[1])))  # type: ignore[arg-type]
        elif isinstance(item, dict):
            result.append(
                SortKey(item["field"], item.get("direction", "asc"))  # type: ignore[arg-type]
            )
        else:
            raise VerboisyError("Invalid sort specification")
    return result


def _inline_urls(goal: str) -> list[str]:
    """Extract sentence URLs without truncating paths or swallowing prose."""
    urls: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for match in re.findall(r"https?://[^\s<>\"'`]+", goal, flags=re.IGNORECASE):
        value = match.rstrip(".,;")
        while (
            value and value[-1] in pairs and value.count(value[-1]) > value.count(pairs[value[-1]])
        ):
            value = value[:-1].rstrip(".,;")
        url = canonical_url(value)
        if url is not None:
            urls.append(url)
    return urls


async def _discover_seeds(
    goal: str,
    spec: TaskSpec,
    policy: SourcePolicy,
    config: Settings,
    plan: ResearchPlan,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Retain the existing discovery hook and call-time API provider/URL callbacks."""
    return await discover_seed_sources(
        goal, spec, policy, config, plan, web_search, _inline_urls, canonical_url
    )


async def _initial_discovery(
    store: ResearchStore,
    rid: str,
    spec: TaskSpec,
    policy: SourcePolicy,
    config: Settings,
    plan: ResearchPlan,
) -> TaskSpec:
    """Discover sources against the saved run's durable, shared request ledger."""
    return await publish_initial_discovery(
        store, rid, spec, policy, config, plan, _discover_seeds, LLMClient
    )


def _declared_identity(identity: Sequence[str], schema: dict[str, Any]) -> list[str]:
    """Validate explicit scalar JSON pointers; never infer entity uniqueness."""
    if isinstance(identity, str | bytes) or not 1 <= len(identity) <= 20:
        raise VerboisyError("Identity requires 1 to 20 scalar JSON pointers")
    fields = scalar_field_schemas(schema)
    result: list[str] = []
    for pointer in identity:
        if not isinstance(pointer, str) or pointer not in fields or "*" in pointer.split("/"):
            raise VerboisyError(
                "Identity pointers must name scalar schema fields without array wildcards"
            )
        if pointer in result:
            raise VerboisyError("Duplicate identity pointer")
        result.append(pointer)
    return result


async def arun(
    *,
    goal: str | None = None,
    schema: str | Path | dict[str, Any] | list[str] | tuple[str, ...] | None = None,
    export: str | Path | Sequence[str | Path] | None = None,
    resume: bool | str = False,
    okresume: bool | str = False,
    headless: bool | None = None,
    max_steps: int | None = None,
    config: Settings | None = None,
    task: TaskSpec | dict[str, Any] | str | Path | None = None,
    identity: Sequence[str] | None = None,
    dataset_sources: Sequence[dict[str, Any]] | None = None,
    dataset_projection: ProjectionPlan | dict[str, Any] | str | Path | None = None,
    include: Sequence[str] | None = None,
    avoid: Sequence[str] | None = None,
    onlyinclude: bool = False,
    strings: bool = False,
    maxrows: int | None = None,
    order: Sequence[SortKey | tuple[str, str] | dict[str, str]] | None = None,
    groupby: str | None = None,
    smartid: str | Path | None = None,
    proof: bool = False,
    research: bool = False,
    mass_unit: str | None = None,
    length_unit: str | None = None,
    date_format: str | None = None,
) -> RunResult:
    """Start or resume evidence-backed research using simple or advanced configuration."""

    display_overrides = {
        key: value
        for key, value in {
            "mass_unit": mass_unit,
            "length_unit": length_unit,
            "date_format": date_format,
        }.items()
        if value is not None
    }
    preferences(display_overrides)  # Validate before opening or mutating the ledger.
    config = (config or Settings()).model_copy()
    display_defaults = config.presentation_defaults()
    if not isinstance(okresume, bool | str) or (isinstance(okresume, str) and not okresume.strip()):
        raise VerboisyError("okresume must be True, False, or a nonempty run id")
    if resume and okresume:
        raise VerboisyError("Choose --resume or --okresume, not both")
    accept_changes = bool(okresume)
    if okresume:
        resume = okresume
    if headless is not None:
        config.headless_browser = headless
    steps = max_steps if max_steps is not None else config.max_steps
    if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0:
        raise VerboisyError("max_steps must be a positive integer")
    if not isinstance(resume, bool | str) or (isinstance(resume, str) and not resume):
        raise VerboisyError("resume must be True, False, or a nonempty run id")
    if maxrows is not None and (isinstance(maxrows, bool) or maxrows <= 0):
        raise VerboisyError("--maxrows must be a positive integer")
    sort_keys = _normalize_sort_keys(order)
    policy = SourcePolicy(tuple(include or ()), tuple(avoid or ()), onlyinclude)
    destinations = _export_paths(export, config.sqlite_db_path)
    input_paths = {
        Path(value).resolve()
        for value in (task, dataset_projection)
        if isinstance(value, str | Path)
    }
    # Only schemas support bracketed inline declarations and trimmed filenames.
    # Task/projection filenames remain literal, even when they start with '['.
    schema_input = schema.strip() if isinstance(schema, str) else schema
    if isinstance(schema_input, str | Path) and not (
        isinstance(schema_input, str) and schema_input.startswith("[")
    ):
        input_paths.add(Path(schema_input).resolve())
    output_files = {
        path
        for destination in destinations
        for path in (
            destination,
            destination.with_suffix(destination.suffix + ".manifest.json"),
            destination.with_suffix(destination.suffix + ".evidence.json"),
            destination.with_suffix(destination.suffix + ".events.json"),
            destination.with_suffix(destination.suffix + ".assets.json"),
            destination.with_name(destination.stem + ".proof.txt"),
        )
    }
    input_paths.add(Path(".env").resolve())
    input_paths.update(config.input_files())
    if smartid is not None:
        input_paths.add(Path(smartid).resolve())
    try:
        validate_output_paths(output_files, input_paths)
    except (OSError, ValueError):
        raise VerboisyError(
            "Export files must differ from schema/task inputs and references"
        ) from None

    if research and any((maxrows, sort_keys, groupby, smartid)):
        raise VerboisyError(
            "--research cannot be combined with --maxrows, ordering, --groupby, or --smartid"
        )
    if resume and any(
        value
        for value in (
            goal is not None,
            schema is not None,
            task is not None,
            identity is not None,
            dataset_sources is not None,
            dataset_projection is not None,
            bool(include),
            bool(avoid),
            onlyinclude,
            strings,
            maxrows is not None,
            bool(sort_keys),
            groupby is not None,
            smartid is not None,
            research,
        )
    ):
        raise VerboisyError(
            "Resume uses its saved goal, schema, source policy, and dataset shaping options"
        )
    if not resume and (not goal or not goal.strip() or schema is None):
        raise VerboisyError("New runs require --goal and --schema")

    store = ResearchStore(config.sqlite_db_path)
    simple_schema = False
    inferred_schema: dict[str, Any] | None = None
    change_notice: str | None = None
    try:
        if resume:
            state = store.load(resume if isinstance(resume, str) else None)
            rid = state["id"]
            # Preflight shaping and output paths before recording a user decision.
            options = saved_product_options(store.events(rid, "product_options"))
            if not destinations:
                destinations = _export_paths(
                    saved_export_destinations(state["export_path"]), config.sqlite_db_path
                )
            saved_inputs = store.events(rid, "export_inputs")
            for entry in saved_inputs:
                input_paths.update(export_input_paths([entry]))
            pending_change(store, rid)
            saved_task = TaskSpec.model_validate_json(state["task_json"])
            input_paths.update(local_source_paths(s.url for s in saved_task.dataset_sources))
            if options.get("smartid"):
                input_paths.add(Path(options["smartid"]).resolve())
            _protect_exports(destinations, input_paths)
            policy = SourcePolicy(**options["source_policy"])
            if store.events(rid, "initial_discovery") and not store.events(rid, "seed_frontier"):
                preflight_initial_discovery(store, rid, policy)
            saved_display = store.events(rid, "presentation_preferences")
            display = resolve_saved_preferences(display_defaults, saved_display, display_overrides)
            # Candidate decoding is independent of the proposed replacement schema.
            # Finish this read-only scan before a decision can revisit the frontier.
            range_evidence = saved_range_evidence(store, rid)
            decision = decide_change(store, rid, accept=accept_changes)
            if decision is not None:
                change_notice = (
                    "* Accepted proposed requirements: " + decision.request.description
                    if accept_changes
                    else "* Proposed changes declined; continuing with the original requirements."
                )
            state = store.load(rid)
            spec = TaskSpec.model_validate_json(state["task_json"])
            target_schema = json.loads(state["schema_json"])
            strings = bool(options.get("strings", False))
            groupby = options.get("groupby")
            smartid = options.get("smartid")
            proof = proof or bool(options.get("proof", False))
            sort_keys = [SortKey(**value) for value in options.get("order", [])]
        else:
            try:
                spec = (
                    task
                    if isinstance(task, TaskSpec)
                    else TaskSpec.model_validate(_json(task) if task is not None else {})
                )
            except ValidationError:
                raise VerboisyError("Invalid task specification") from None
            if dataset_sources is not None:
                try:
                    declared_sources = TaskSpec.model_validate(
                        {"dataset_sources": dataset_sources}
                    ).dataset_sources
                except ValidationError:
                    raise VerboisyError("Invalid dataset source declarations") from None
                if spec.dataset_sources and spec.dataset_sources != declared_sources:
                    raise VerboisyError("Dataset sources conflict with task.dataset_sources")
                spec = spec.model_copy(update={"dataset_sources": declared_sources})
            if dataset_projection is not None:
                try:
                    projection = (
                        dataset_projection
                        if isinstance(dataset_projection, ProjectionPlan)
                        else ProjectionPlan.model_validate(_json(dataset_projection))
                    )
                except ValidationError:
                    raise VerboisyError("Invalid dataset projection plan") from None
                if not spec.dataset_sources:
                    raise VerboisyError("Dataset projection requires declared dataset sources")
                projected_sources = []
                for source in spec.dataset_sources:
                    if source.projection is not None and source.projection != projection:
                        raise VerboisyError("Projection conflicts with declared source plan")
                    projected_sources.append(source.model_copy(update={"projection": projection}))
                spec = spec.model_copy(update={"dataset_sources": projected_sources})
            if spec.dataset_sources and spec.seed_urls:
                raise VerboisyError("Declared dataset sources cannot be mixed with browser seeds")
            schema_value = cast(
                str | Path | dict[str, Any] | list[str] | tuple[str, ...],
                schema,
            )
            target_schema, simple_schema = _schema(
                schema_value,
                strings=strings,
            )
            if identity is not None:
                declared = _declared_identity(identity, target_schema)
                if spec.identity_fields and spec.identity_fields != declared:
                    raise VerboisyError("Identity conflicts with task.identity_fields")
                spec = spec.model_copy(update={"identity_fields": declared})
            inferred_schema = target_schema if simple_schema else None
            updates: dict[str, Any] = {
                "avoided_hosts": list(dict.fromkeys([*spec.avoided_hosts, *policy.avoid]))
            }
            if simple_schema and task is None:
                updates["csv_mode"] = "spreadsheet"
            if maxrows is not None:
                updates["target_records"] = maxrows
            if policy.onlyinclude:
                updates["allowed_hosts"] = list(policy.include)
            if research:
                updates["max_depth"] = max(spec.max_depth, 8)
                updates["max_pages"] = max(spec.max_pages, 1000)
                updates["max_links_per_page"] = max(spec.max_links_per_page, 500)
            spec = spec.model_copy(update=updates)

            validate_time_series(
                spec.time_series,
                _schema_fields(target_schema),
                groupby,
                bool(sort_keys),
                spec.identity_fields,
            )
            plan = build_research_plan(
                target_schema,
                spec.target_records,
            )

            if spec.target_records and target_schema["type"] == "array":
                minimum = target_schema.get("minItems", 0)
                maximum = target_schema.get("maxItems", 100000)
                if not minimum <= spec.target_records <= maximum:
                    raise VerboisyError("Target conflicts with schema collection limits")
            input_paths.update(local_source_paths(s.url for s in spec.dataset_sources))
            _protect_exports(destinations, input_paths)
            stored_exports = (
                json.dumps([str(path) for path in destinations]) if destinations else None
            )
            rid = store.create(
                goal or "",
                target_schema,
                spec,
                stored_exports,
            )

            store.event(rid, "export_inputs", {"paths": sorted(str(path) for path in input_paths)})
            store.event(
                rid,
                "research_plan",
                plan.as_event(),
            )

            store.event(
                rid,
                "product_options",
                {
                    "strings": strings,
                    "groupby": groupby,
                    "smartid": str(smartid) if smartid else None,
                    "proof": proof,
                    "research": research,
                    "source_policy": {
                        "include": list(policy.include),
                        "avoid": list(policy.avoid),
                        "onlyinclude": policy.onlyinclude,
                    },
                    "order": [key.__dict__ for key in sort_keys],
                    "schema_inferred": simple_schema,
                },
            )
            if not spec.dataset_sources:
                store.event(rid, "initial_discovery", {"status": "pending"})
            state = store.load(rid)

        validate_time_series(
            spec.time_series,
            _schema_fields(target_schema),
            groupby,
            bool(sort_keys),
            spec.identity_fields,
        )
        if not resume:
            saved_display = store.events(rid, "presentation_preferences")
            display = resolve_saved_preferences(display_defaults, saved_display, display_overrides)
        if not saved_display or display_overrides:
            store.event(rid, "presentation_preferences", display.model_dump())

        if resume:
            offered = offer_saved_range_change(store, rid, saved_evidence=range_evidence)
            if offered is not None:
                return _proposal_pause_result(store, rid, offered)

        if store.events(rid, "initial_discovery") and not store.events(rid, "seed_frontier"):
            plan = build_research_plan(target_schema, spec.target_records)
            spec = await _initial_discovery(store, rid, spec, policy, config, plan)
            state = store.load(rid)

        runner: ResearchRunner | None = None
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
                    "search_request_budget": config.search_request_budget,
                },
            )
            runner = ResearchRunner(store, rid, config)
            if spec.dataset_sources:
                await run_dataset_sources(runner, steps)
            else:
                await runner.run(steps)

        state = store.load(rid)
        if state["reason"] == "proposed_changes":
            offered = pending_change(store, rid)
            if offered is None:
                raise VerboisyError("Paused change proposal is missing")
            return _proposal_pause_result(store, rid, offered)
        if state["status"] == "COMPLETED" and spec.dataset_sources:
            validate_dataset_evidence(store, rid, spec)
        dataset_consistency = None
        if spec.dataset_sources:
            report_runner = runner or ResearchRunner(store, rid, config)
            dataset_consistency = {
                "scope": "accepted_records",
                "gaps": list(report_runner.dataset_consistency_gaps()),
                "repairs": list(report_runner.dataset_consistency_repairs()),
            }
        prepared = prepare_output(
            store,
            rid,
            target_schema,
            spec,
            display,
            schema_fields=_schema_fields(target_schema),
            strings=strings,
            groupby=groupby,
            sort_keys=sort_keys,
            smartid=smartid,
            schema_inferred=simple_schema or bool(inferred_schema),
            change_notice=change_notice,
        )
        artifacts = write_output(
            store,
            rid,
            prepared,
            destinations,
            target_schema,
            spec,
            display,
            proof=proof,
            dataset_consistency=dataset_consistency,
        )
        return RunResult(
            run_id=rid,
            records=prepared.rows,
            export_path=destinations[0] if destinations else None,
            db_path=store.path,
            completed=state["status"] == "COMPLETED",
            status=state["status"],
            stop_reason=state["reason"],
            manifest_path=artifacts.manifests[0] if artifacts.manifests else None,
            export_paths=destinations,
            manifest_paths=artifacts.manifests,
            proof_path=artifacts.proof_path,
            notices=tuple(prepared.notices),
            inferred_schema=inferred_schema,
            dataset_consistency=dataset_consistency,
        )
    finally:
        store.close()


def run(**kwargs: Any) -> RunResult:
    """Synchronous wrapper; notebooks should await :func:`arun`."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(arun(**kwargs))
    raise VerboisyError("run() cannot execute inside an event loop; use await arun(...)")
