# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Typer CLI for goal-driven, evidence-backed web research."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from verboisy import __version__
from verboisy.api import run
from verboisy.cli.streaming import stream_command, stream_status
from verboisy.cli.ui import CLIUserInterface
from verboisy.dataset_formats import MIME_TYPES, format_capabilities
from verboisy.product import SortKey
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.logger import setup_logging

ROOT_HELP = r"""
Verboisy turns a research goal and requested columns into an evidence-backed dataset.

Give Verboisy a goal, a schema, and optionally source rules, dataset shaping rules,
and export destinations.

\b
Minimum new run:
  verboisy run --goal "..." --schema '[field1,field2]' --export output.csv

\b
Resume the latest incomplete run:
  verboisy run --resume
"""


ROOT_EPILOG = r"""
\b
RUN OPTIONS

\b
Basic
  --goal, -g TEXT          Required for a new run. Describe what data to find.
  --schema, -s TEXT        Required for a new run. Example: [name,price,website].
  --export, -e PATH        Optional CSV/JSON output. Repeat for multiple outputs.

\b
Source control
  --include DOMAIN         Include or prefer a domain. May be repeated.
  --avoid DOMAIN           Never visit or use a domain. May be repeated.
  --onlyinclude            Restrict research to --include domains only.
  --dataset-source FORMAT=URL  Declared format (see verboisy formats); repeatable.
  --dataset-file FORMAT=PATH   Local source within DATASET_LOCAL_ROOTS; repeatable.
  --dataset-projection PATH   Explicit JSON field mapping and conversion plan.

\b
Dataset shaping
  --identity POINTER       Explicit entity key; repeat for compound keys, e.g. /namespace and /sku.
  --strings                Export requested fields as strings.
  --maxrows INTEGER        Maximum accepted rows desired.
  --orderby FIELD          Sort ascending. May be repeated.
  --orderbydesc FIELD      Sort descending. May be mixed with --orderby.
  --groupby FIELD          Group rows and aggregate compatible numeric fields.

\b
Dataset relationships
  --smartid PATH           Link rows to IDs in a previous Verboisy CSV/JSON dataset.

\b
Research and proof
  --research               Broader research mode. Uses more time and API budget.
  --proof                  Write a human-readable provenance report.

\b
Execution and recovery
  --resume, -r [RUN_ID]    Resume RUN_ID. Bare --resume uses latest incomplete run.
  --okresume [RUN_ID]      Accept the saved proposed changes and resume.
  --max-steps, -m INTEGER  Limit browser page visits for this invocation.
  --headless / --headed    Browser visibility override. Default is headless.

\b
Important rules
  --goal and --schema are required when starting a new run.
  --onlyinclude requires at least one --include.
  --proof requires at least one --export.
  --orderby and --orderbydesc may be repeated and mixed.
  Ordering arguments are applied in the order they are supplied.
  Identity keys must be chosen explicitly; a name alone need not identify an entity.
  Missing identity values cannot be accepted as an entity key.
  Missing information becomes null or an empty CSV cell.
  Normal browser operation is headless. Use --headed only for debugging.

\b
Examples

\b
  verboisy run \
    --goal "Find white laptops under €1000" \
    --schema '[name,brand,color,price,screen_size]' \
    --maxrows 20 \
    --orderby price \
    --proof \
    --export laptops.csv

\b
  verboisy run \
    --goal "Find AI startups in Europe" \
    --schema '[name,country,website,funding]' \
    --avoid example.com \
    --maxrows 100 \
    --export startups.json

\b
  verboisy run \
    --goal "Find universities in Italy" \
    --schema '[name,city,website]' \
    --include wikipedia.org \
    --include unibo.it \
    --export universities.csv

  verboisy run --resume
"""


class ResumeGroup(TyperGroup):
    """Normalize optional resume values and retain mixed sort argument order."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        normalized: list[str] = []
        sorts: list[dict[str, str]] = []
        index = 0

        while index < len(args):
            arg = args[index]

            if arg in ("--resume", "-r", "--okresume") and (
                index + 1 == len(args) or args[index + 1].startswith("-")
            ):
                normalized.append(
                    "--okresume=__latest__" if arg == "--okresume" else "--resume=__latest__"
                )
                index += 1
                continue

            if arg in ("--orderby", "--orderbydesc") and index + 1 < len(args):
                sorts.append(
                    {
                        "field": args[index + 1],
                        "direction": "asc" if arg == "--orderby" else "desc",
                    }
                )

            elif arg.startswith("--orderby="):
                sorts.append(
                    {
                        "field": arg.split("=", 1)[1],
                        "direction": "asc",
                    }
                )

            elif arg.startswith("--orderbydesc="):
                sorts.append(
                    {
                        "field": arg.split("=", 1)[1],
                        "direction": "desc",
                    }
                )

            normalized.append(arg)
            index += 1

        ctx.meta["verboisy_sort_order"] = sorts
        return super().parse_args(ctx, normalized)


app = typer.Typer(
    name="verboisy",
    cls=ResumeGroup,
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help=ROOT_HELP.replace(r"\b", "\b"),
    epilog=ROOT_EPILOG.replace(r"\b", "\b"),
    context_settings={"max_content_width": 120},
)


@app.callback()
def main() -> None:
    """Verboisy command group."""


@app.command("run")
def run_agent(
    ctx: typer.Context,
    goal: Annotated[
        str | None,
        typer.Option(
            "--goal",
            "-g",
            help=("Required for a new run; describe the dataset " "you want in ordinary language."),
        ),
    ] = None,
    schema: Annotated[
        str | None,
        typer.Option(
            "--schema",
            "-s",
            help=(
                "Required for a new run; use [name,price,...] " "or an explicit JSON Schema path."
            ),
        ),
    ] = None,
    export: Annotated[
        list[Path] | None,
        typer.Option(
            "--export",
            "-e",
            help=("Optional CSV/JSON destination; repeat for " "multiple exports."),
        ),
    ] = None,
    dataset_projection: Annotated[
        Path | None,
        typer.Option(
            "--dataset-projection", help="Explicit JSON projection plan for declared sources."
        ),
    ] = None,
    dataset_source: Annotated[
        list[str] | None,
        typer.Option(
            "--dataset-source",
            help="Declared dataset as csv=URL, json=URL or jsonl=URL; repeatable.",
        ),
    ] = None,
    dataset_file: Annotated[
        list[str] | None,
        typer.Option(
            "--dataset-file",
            help=(
                "Local dataset as csv=PATH, json=PATH or jsonl=PATH; "
                "requires DATASET_LOCAL_ROOTS."
            ),
        ),
    ] = None,
    identity: Annotated[
        list[str] | None,
        typer.Option(
            "--identity",
            help="Explicit entity-key JSON pointer; repeat for a compound key. Example: /sku.",
        ),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Optional domain to include/prefer; repeatable.",
        ),
    ] = None,
    avoid: Annotated[
        list[str] | None,
        typer.Option(
            "--avoid",
            help="Optional domain to exclude completely; repeatable.",
        ),
    ] = None,
    onlyinclude: Annotated[
        bool,
        typer.Option(
            "--onlyinclude",
            help="Use only domains supplied with --include.",
        ),
    ] = False,
    strings: Annotated[
        bool,
        typer.Option(
            "--strings",
            help="Export requested simple-schema fields as strings.",
        ),
    ] = False,
    maxrows: Annotated[
        int | None,
        typer.Option(
            "--maxrows",
            min=1,
            help="Maximum accepted dataset rows desired.",
        ),
    ] = None,
    orderby: Annotated[
        list[str] | None,
        typer.Option(
            "--orderby",
            help=("Sort ascending; repeatable and mixable " "with --orderbydesc."),
        ),
    ] = None,
    orderbydesc: Annotated[
        list[str] | None,
        typer.Option(
            "--orderbydesc",
            help=("Sort descending; argument order determines " "sort priority."),
        ),
    ] = None,
    groupby: Annotated[
        str | None,
        typer.Option(
            "--groupby",
            help=("Group rows and deterministically aggregate " "numeric fields."),
        ),
    ] = None,
    smartid: Annotated[
        Path | None,
        typer.Option(
            "--smartid",
            help=("Link rows conservatively to IDs in a previous " "Verboisy CSV/JSON dataset."),
        ),
    ] = None,
    research: Annotated[
        bool,
        typer.Option(
            "--research",
            help=("Broader research mode; may use substantially " "more time and API budget."),
        ),
    ] = False,
    proof: Annotated[
        bool,
        typer.Option(
            "--proof",
            help="Write a human-readable provenance report.",
        ),
    ] = False,
    resume: Annotated[
        str | None,
        typer.Option(
            "--resume",
            "-r",
            help=("Resume RUN_ID; bare --resume uses the latest " "incomplete run."),
        ),
    ] = None,
    okresume: Annotated[
        str | None,
        typer.Option(
            "--okresume",
            help=(
                "Accept saved proposed requirements and resume RUN_ID; "
                "bare uses latest incomplete run."
            ),
        ),
    ] = None,
    mass_unit: Annotated[
        str | None, typer.Option("--mass-unit", help="Display mass: kg, lb, or source.")
    ] = None,
    length_unit: Annotated[
        str | None, typer.Option("--length-unit", help="Display length: m, ft, or source.")
    ] = None,
    date_format: Annotated[
        str | None, typer.Option("--date-format", help="Display dates: dmy, mdy, iso, or source.")
    ] = None,
    max_steps: Annotated[
        int | None,
        typer.Option(
            "--max-steps",
            "-m",
            min=1,
            help="Optional page-visit limit for this invocation.",
        ),
    ] = None,
    headless: Annotated[
        bool | None,
        typer.Option(
            "--headless/--headed",
            help="Browser visibility override; default is headless.",
        ),
    ] = None,
) -> None:
    """Start or resume an evidence-backed research run."""

    del orderby, orderbydesc

    CLIUserInterface.print_header(
        f"Verboisy {__version__}",
        "Autonomous web research",
    )

    sorts = [
        SortKey(**item)
        for item in ctx.find_root().meta.get(
            "verboisy_sort_order",
            [],
        )
    ]

    try:
        config = Settings()
        setup_logging(config)

        sources = None
        if dataset_source:
            sources = []
            for declaration in dataset_source:
                fmt, separator, url = declaration.partition("=")
                if not separator or fmt not in MIME_TYPES or not url:
                    raise VerboisyError(
                        "--dataset-source requires FORMAT=URL; see verboisy formats (e.g. json=URL)"
                    )
                sources.append({"format": fmt, "url": url})

        if dataset_file:
            sources = sources or []
            for declaration in dataset_file:
                fmt, separator, local_path = declaration.partition("=")
                if not separator or fmt not in MIME_TYPES or not local_path:
                    raise VerboisyError(
                        "--dataset-file requires FORMAT=PATH; see verboisy formats (e.g. json=PATH)"
                    )
                sources.append({"format": fmt, "url": Path(local_path).absolute().as_uri()})

        result = run(
            goal=goal,
            schema=schema,
            export=export,
            identity=identity,
            dataset_sources=sources,
            dataset_projection=dataset_projection,
            include=include,
            avoid=avoid,
            onlyinclude=onlyinclude,
            strings=strings,
            maxrows=maxrows,
            order=sorts,
            groupby=groupby,
            smartid=smartid,
            research=research,
            proof=proof,
            resume=True if resume == "__latest__" else (resume or False),
            okresume=True if okresume == "__latest__" else (okresume or False),
            headless=headless,
            max_steps=max_steps,
            mass_unit=mass_unit,
            length_unit=length_unit,
            date_format=date_format,
            config=config,
        )

    except KeyboardInterrupt:
        CLIUserInterface.print_error(
            "Research interrupted. Committed records remain in SQLite.\n"
            "Resume with: verboisy run --resume"
        )
        raise typer.Exit(130) from None

    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        CLIUserInterface.print_error(f"Invalid configuration fields: {fields}")
        raise typer.Exit(1) from None

    except (VerboisyError, OSError) as exc:
        CLIUserInterface.print_error(str(exc))
        raise typer.Exit(1) from None

    except Exception as exc:
        CLIUserInterface.print_error(
            f"Execution failed ({type(exc).__name__}). " "Committed records remain in SQLite."
        )
        raise typer.Exit(1) from None

    typer.echo(f"Run ID:\n{result.run_id}\n")

    if goal:
        typer.echo(f"Task:\n{goal.strip()}\n")

    for notice in result.notices:
        typer.echo(notice)

    typer.echo(f"Status: {result.status}; " f"{len(result.records)} accepted rows")

    dataset_consistency = getattr(result, "dataset_consistency", None)
    if dataset_consistency is not None:
        for gap in dataset_consistency["gaps"]:
            typer.echo(f"Dataset gap: {gap}")
        for repair in dataset_consistency["repairs"]:
            typer.echo(
                f"Repair record {repair['record_id']} "
                f"at {repair['pointer']}: {repair['reason']}"
            )

    show_artifacts = result.completed or bool(result.records)

    if show_artifacts:
        for path in result.export_paths:
            typer.echo(f"Dataset: {path}")

        for path in result.manifest_paths:
            typer.echo(f"Manifest: {path}")

        if result.proof_path:
            typer.echo(f"Proof: {result.proof_path}")

    CLIUserInterface.display_results_table(result.records)

    if result.completed:
        CLIUserInterface.print_success("Completed")
        CLIUserInterface.print_signoff()

    else:
        if result.stop_reason == "provider_rate_limit":
            CLIUserInterface.print_error(
                "OpenAI rate limit reached. "
                "Research progress was saved.\n"
                "Resume with: verboisy run --resume"
            )
        else:
            CLIUserInterface.print_error(
                f"Incomplete: {result.stop_reason}. " f"Resume with --resume {result.run_id}"
            )

        raise typer.Exit(1 if result.status == "FAILED" else 2)


@app.command("changes")
def research_changes(
    run_id: Annotated[str, typer.Option("--run-id", help="Saved run ID.")],
    database: Annotated[Path | None, typer.Option("--database")] = None,
    proposal: Annotated[
        Path | None,
        typer.Option("--proposal", help="Save and offer exact requirements from a JSON file."),
    ] = None,
) -> None:
    """Inspect a pending proposal, or submit one and pause research."""
    import json
    from contextlib import closing

    from verboisy.storage.changes import pending_change, propose_change
    from verboisy.storage.research import ResearchStore

    try:
        if not run_id.strip():
            raise VerboisyError("Choose a nonempty run ID")
        value = json.loads(proposal.read_text(encoding="utf-8")) if proposal is not None else None
        path = str(database) if database is not None else Settings().sqlite_db_path
        with closing(ResearchStore(path, read_only=proposal is None)) as store:
            change = (
                propose_change(store, run_id, value)
                if proposal is not None
                else pending_change(store, run_id)
            )
            if change is None:
                typer.echo("* No pending proposal. Use --resume to continue this run.")
            else:
                typer.echo("* Proposed changes: " + change.request.description)
                typer.echo(change.model_dump_json(indent=2, by_alias=True))
                typer.echo(f"* Keep current requirements: verboisy run --resume {run_id}")
                typer.echo(f"* Accept these changes: verboisy run --okresume {run_id}")
    except (VerboisyError, OSError, ValueError):
        CLIUserInterface.print_error("Cannot inspect or save the proposed requirements")
        raise typer.Exit(1) from None


@app.command("assets")
def dataset_assets(
    database: Annotated[Path, typer.Option("--database", help="Existing research SQLite ledger.")],
    run_id: Annotated[str, typer.Option("--run-id")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """List verified saved dataset assets as JSON; no downloads or model calls."""
    import json

    from verboisy.storage.inventory import inspect_dataset_assets

    try:
        report = inspect_dataset_assets(database, run_id, limit=limit)
    except (VerboisyError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("native-config")
def native_configuration() -> None:
    """Inspect native backend selection and fingerprints without loading a binary."""
    import json

    from verboisy.evidence.native_configuration import inspect_native_configuration

    try:
        report = inspect_native_configuration()
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("model-config")
def model_configuration() -> None:
    """Show active model settings without provider calls or credential values."""
    import json

    from verboisy.llm.configuration import inspect_model_configuration

    try:
        report = inspect_model_configuration()
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        typer.echo(f"Invalid configuration fields: {fields}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("presentation-config")
def presentation_configuration() -> None:
    """Show configured display defaults without opening a ledger or contacting providers."""
    import json

    try:
        defaults = Settings().presentation_defaults()
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        typer.echo(f"Invalid configuration fields: {fields}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "configuration_version": "1",
                "scope": "configured_defaults",
                "defaults": defaults.model_dump(),
                "precedence": [
                    "explicit_run_options",
                    "saved_run_preferences",
                    "configured_defaults",
                    "built_in_defaults",
                ],
            },
            indent=2,
        )
    )


@app.command("status")
def research_status(
    run_id: Annotated[str, typer.Option("--run-id")],
    database: Annotated[
        Path | None, typer.Option("--database", help="Existing ledger; defaults to SQLITE_DB_PATH.")
    ] = None,
) -> None:
    """Inspect persisted progress and accounting for any saved run without resuming."""
    import json

    from verboisy.storage.diagnostics import inspect_research_status

    try:
        selected = database if database is not None else Path(Settings().sqlite_db_path)
        report = inspect_research_status(selected, run_id)
    except ValidationError as exc:
        fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
        typer.echo(f"Invalid configuration fields: {fields}", err=True)
        raise typer.Exit(1) from None
    except (VerboisyError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("runs")
def research_runs(
    database: Annotated[
        Path | None, typer.Option("--database", help="Existing ledger; defaults to SQLITE_DB_PATH.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """List saved runs and eligibility for dataset repair inspection, without writes."""
    import json

    from verboisy.storage.diagnostics import inspect_research_runs
    from verboisy.utils.config import Settings

    try:
        selected = database if database is not None else Path(Settings().sqlite_db_path)
        report = inspect_research_runs(selected, limit=limit)
    except (VerboisyError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("repairs")
def dataset_repairs(
    database: Annotated[Path, typer.Option("--database", help="Existing research SQLite ledger.")],
    run_id: Annotated[str, typer.Option("--run-id")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """Inspect current dataset gaps and planned repairs without resuming the run."""
    import json

    from verboisy.storage.diagnostics import inspect_dataset_repairs

    try:
        report = inspect_dataset_repairs(database, run_id, limit=limit)
    except (VerboisyError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


@app.command("map")
def map_dataset(
    database: Annotated[Path, typer.Option("--database", help="Existing research SQLite ledger.")],
    run_id: Annotated[str, typer.Option("--run-id")],
    asset_id: Annotated[str, typer.Option("--asset-id")],
    output: Annotated[Path, typer.Option("--output", help="New JSON review report.")],
    aliases: Annotated[
        Path | None, typer.Option("--aliases", help="Explicit target-to-source aliases.")
    ] = None,
    projection: Annotated[
        Path | None, typer.Option("--projection", help="Review an explicit JSON projection plan.")
    ] = None,
    plan: Annotated[
        Path | None,
        typer.Option("--plan", help="Approve and write a fully validated projection plan."),
    ] = None,
) -> None:
    """Review a saved dataset mapping; no downloads or model calls."""
    from verboisy.extractor.review import review_mapping

    try:
        report = review_mapping(
            database,
            run_id,
            asset_id,
            output,
            aliases_path=aliases,
            plan_path=plan,
            projection_path=projection,
        )
    except (VerboisyError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Mapping review: {output}; decision: {report['decision']}")
    if plan is not None:
        if report["decision"] == "blocked":
            typer.echo(str(report["validation_reason"]), err=True)
            raise typer.Exit(2)
        typer.echo(f"Projection plan: {plan}; use --dataset-projection for a new run.")


@app.command()
def setup() -> None:
    """Provision Chromium and check startup; no model calls."""

    import asyncio

    from verboisy.browser.context import BrowserManager

    async def check() -> None:
        manager = BrowserManager(Settings(browser_auto_install=True))

        try:
            await manager.start()

        finally:
            await manager.close()

    try:
        asyncio.run(check())

    except VerboisyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None

    typer.echo("Chromium is ready.")


@app.command()
def doctor() -> None:
    """Check configuration without printing credentials or model requests."""

    import importlib.metadata

    config = Settings()

    typer.echo(f"Verboisy {__version__}; " f"Playwright {importlib.metadata.version('playwright')}")
    typer.echo(f"Model: {config.litellm_model}; " f"sandbox: {config.browser_sandbox}")
    typer.echo(f"Search: {config.search_provider}; " f"browser headless: {config.headless_browser}")
    typer.echo(f"Automatic browser setup: " f"{config.browser_auto_install}")
    typer.echo("Run verboisy setup to check browser startup.")


if __name__ == "__main__":
    app()


@app.command("formats")
def formats() -> None:
    """Inspect file support without model calls, acquisition or database access."""
    import json

    typer.echo(json.dumps(format_capabilities(), ensure_ascii=False, indent=2))


app.command("stream")(stream_command)

app.command("stream-status")(stream_status)
