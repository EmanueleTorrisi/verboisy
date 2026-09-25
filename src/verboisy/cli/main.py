"""Typer CLI using the same public API as Python callers."""

from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from verboisy import __version__
from verboisy.api import run
from verboisy.cli.ui import CLIUserInterface
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError
from verboisy.utils.logger import setup_logging


class ResumeGroup(TyperGroup):
    """Normalize Click's optional-value resume flag before parsing the command."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        normalized = []
        for index, arg in enumerate(args):
            if arg in ("--resume", "-r") and (
                index + 1 == len(args) or args[index + 1].startswith("-")
            ):
                normalized.append("--resume=__latest__")
            else:
                normalized.append(arg)
        return super().parse_args(ctx, normalized)


app = typer.Typer(name="verboisy", cls=ResumeGroup, add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Autonomous web research and schema-validated extraction."""


@app.command("run")
def run_agent(
    goal: Annotated[str | None, typer.Option("--goal", "-g", help="Research goal.")] = None,
    schema_path: Annotated[
        Path | None, typer.Option("--schema", "-s", help="JSON Schema path.")
    ] = None,
    export_path: Annotated[
        Path | None, typer.Option("--export", "-e", help="JSON or CSV destination.")
    ] = None,
    resume: Annotated[
        str | None,
        typer.Option(
            "--resume", "-r", help="Optional run id; bare flag selects latest incomplete."
        ),
    ] = None,
    max_steps: Annotated[
        int | None, typer.Option("--max-steps", "-m", min=1, help="Steps for this invocation.")
    ] = None,
    headless: Annotated[
        bool | None, typer.Option("--headless/--headed", help="Override browser visibility.")
    ] = None,
) -> None:
    """Start or resume a run. Incomplete budgets exit 2; interruption exits 130."""
    CLIUserInterface.print_header(f"Verboisy {__version__}", "Autonomous web research")
    try:
        config = Settings()
        setup_logging(config)
        result = run(
            goal=goal,
            schema=schema_path,
            export=export_path,
            resume=True if resume == "__latest__" else (resume or False),
            headless=headless,
            max_steps=max_steps,
            config=config,
        )
    except KeyboardInterrupt:
        CLIUserInterface.print_error(
            "Interrupted. Committed records remain in SQLite. Resume with verboisy run --resume."
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
            f"Execution failed ({type(exc).__name__}). Committed records remain in SQLite."
        )
        raise typer.Exit(1) from None
    CLIUserInterface.print_success(f"run_id: {result.run_id}; {len(result.records)} records saved")
    CLIUserInterface.display_results_table(result.records)
    if result.completed:
        if result.export_path is not None:
            CLIUserInterface.print_success(f"Exported to {result.export_path}")
        CLIUserInterface.print_success("Completed")
    else:
        CLIUserInterface.print_error(
            f"Incomplete: {result.stop_reason}. Resume with --resume {result.run_id}"
        )
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
